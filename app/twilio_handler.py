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


async def handle_twilio_websocket(websocket: WebSocket, session_id: str, settings: Settings) -> None:
    start = time.time()
    await websocket.accept()

    _, call_data = await parse_telephony_websocket(websocket)
    stream_sid = call_data['stream_id']
    call_sid = call_data['call_id']

    serializer = TwilioFrameSerializer(
        stream_sid=stream_sid,
        call_sid=call_sid,
        account_sid=settings.twilio_account_sid or None,
        auth_token=settings.twilio_auth_token or None,
        params=TwilioFrameSerializer.InputParams(auto_hang_up=False),
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            vad_enabled=False,
            serializer=serializer,
            session_timeout=1800,
        ),
    )

    pipeline, llm = create_realtime_pipeline(transport, settings)
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
            allow_interruptions=True,
        ),
        idle_timeout_secs=300,
        enable_tracing=False,
        enable_turn_tracking=False,
        conversation_id=session_id,
    )
    task.set_reached_downstream_filter(())

    @transport.event_handler('on_client_connected')
    async def on_client_connected(_transport: object, _client: object) -> None:
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler('on_client_disconnected')
    async def on_client_disconnected(_transport: object, _client: object) -> None:
        await task.cancel()

    runner = PipelineRunner()
    logger.info('twilio_session_started', session_id=session_id, stream_sid=stream_sid, call_sid=call_sid)
    try:
        await runner.run(task)
    finally:
        logger.info('twilio_session_finished', session_id=session_id, duration_sec=round(time.time() - start, 2))
