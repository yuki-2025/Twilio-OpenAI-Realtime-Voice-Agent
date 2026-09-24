from __future__ import annotations

import time

import structlog
from fastapi import WebSocket
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.runner.utils import parse_telephony_websocket
from pipecat.serializers.twilio import TwilioFrameSerializer
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport

from app.config import Settings
from app.realtime import create_realtime_pipeline

logger = structlog.get_logger(__name__)


def resolve_greeting(call_body: dict, settings: Settings) -> str:
    """Pick the opening line from the 'direction' <Parameter> sent by our TwiML."""
    if call_body.get('direction') == 'outbound':
        return settings.agent_outbound_greeting
    return settings.agent_greeting


async def handle_twilio_websocket(websocket: WebSocket, session_id: str, settings: Settings) -> None:
    start = time.time()
    await websocket.accept()

    _, call_data = await parse_telephony_websocket(websocket)
    stream_sid = call_data['stream_id']
    call_sid = call_data['call_id']
    # Custom <Parameter> values from the TwiML <Stream>; empty for plain inbound calls.
    call_body = call_data.get('body') or {}
    direction = call_body.get('direction', 'inbound')

    # 把 Twilio WebSocket 消息转成 Pipecat 可处理的帧
    # 反向把 Pipecat 输出帧转回 Twilio 需要的格式
    # auto_hang_up=False 表示不自动挂断。
    # 因为 Pipecat 可能会在没有收到更多输入的情况下继续输出（例如，LLM 生成了一个长响应），
    # 所以我们不希望在这种情况下自动挂断电话。
    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=settings.twilio_account_sid or None,
        auth_token=settings.twilio_auth_token or None,
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )

    # 输入输出管道
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True, #接收来电方音频
            audio_out_enabled=True, #向来电方回放语音
            add_wav_header=False,
            vad_enabled=False, #这里不在 transport 层做 VAD
            serializer=serializer, #使用上面 Twilio 序列化规则
            session_timeout=1800, # 30分钟无活动就断开连接，避免资源泄露
        ),
    )
    
    pipeline, llm = create_realtime_pipeline(transport, settings, greeting=resolve_greeting(call_body, settings))
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            allow_interruptions=True,
        ),
        idle_timeout_secs=300, #空闲 5 分钟超时
        enable_tracing=False,
        enable_turn_tracking=False,
        conversation_id=session_id, #绑定会话 ID
    )
    task.set_reached_downstream_filter(()) #通常表示不过滤下游到达事件（保留默认全通）。

    @transport.event_handler('on_client_connected')
    async def on_client_connected(_transport: object, _client: object) -> None:
        await task.queue_frames([LLMRunFrame()]) #触发模型开始运行

    @transport.event_handler('on_client_disconnected')
    async def on_client_disconnected(_transport: object, _client: object) -> None:
        await task.cancel() #客户断开连接时取消任务，释放资源

    runner = PipelineRunner()
    logger.info('twilio_session_started', session_id=session_id, stream_sid=stream_sid, call_sid=call_sid, direction=direction)
    try:
        await runner.run(task) #运行管道，直到完成或被取消
    finally:
        logger.info('twilio_session_finished', session_id=session_id, duration_sec=round(time.time() - start, 2))
        # 确保结束时一定记录时长日志