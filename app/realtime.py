from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.services.openai.realtime.events import (
    AudioConfiguration,
    AudioInput,
    AudioOutput,
    InputAudioNoiseReduction,
    InputAudioTranscription,
    SemanticTurnDetection,
    SessionProperties,
)
from pipecat.services.openai.realtime.llm import OpenAIRealtimeLLMService
from pipecat.turns.user_start import ExternalUserTurnStartStrategy
from pipecat.turns.user_stop import ExternalUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies

from app.config import Settings

# (role, text, iso8601_timestamp) where role is 'user' or 'agent'
TranscriptCallback = Callable[[str, str, str], Awaitable[None]]

_WHITESPACE_RE = re.compile(r'\s+')


def create_context_aggregator(instructions: str, greeting: str) -> LLMContextAggregatorPair:
    context = LLMContext(
        messages=[
            {'role': 'system', 'content': instructions},
            {'role': 'user', 'content': f'Say to the caller: "{greeting}"'},
        ]
    )
    # OpenAI Realtime detects turns server-side and proposes turn boundaries; the external
    # strategies turn those proposals into barge-in interruptions. Pipecat would pick the same
    # settings automatically from the service's startup metadata, but setting them explicitly
    # keeps behaviour independent of that handshake. Without them, the default local strategies
    # treat the caller transcript (which arrives after the agent has started replying) as a
    # barge-in and cut every reply short.
    # The stop strategy is pre-set to wait_for_transcript=False, which is what realtime mode
    # would switch it to anyway; pre-setting it avoids a warning about mutating our strategies.
    turn_strategies = UserTurnStrategies(
        start=[ExternalUserTurnStartStrategy()],
        stop=[ExternalUserTurnStopStrategy(wait_for_transcript=False)],
    )
    return LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(user_turn_strategies=turn_strategies),
        realtime_service_mode=True,
    )


def attach_transcript_handlers(aggregator: LLMContextAggregatorPair, on_transcript: TranscriptCallback) -> None:
    """Report each finished caller and agent turn as (role, text, timestamp)."""

    async def report(role: str, content: str | None, timestamp: str) -> None:
        text = _WHITESPACE_RE.sub(' ', content or '').strip()
        if text:
            await on_transcript(role, text, timestamp)

    # In realtime mode the caller text is only final once written to context, which happens
    # shortly after the agent reply starts; on_user_turn_stopped carries no text in this mode.
    @aggregator.user().event_handler('on_user_turn_message_added')
    async def _on_user_message(_aggregator, message) -> None:
        await report('user', message.content, message.timestamp)

    @aggregator.assistant().event_handler('on_assistant_turn_stopped')
    async def _on_assistant_turn(_aggregator, message) -> None:
        await report('agent', message.content, message.timestamp)


def create_realtime_pipeline(
    transport,
    settings: Settings,
    instructions: str | None = None,
    greeting: str | None = None,
    on_transcript: TranscriptCallback | None = None,
):
    session_properties = SessionProperties(
        instructions=instructions or settings.agent_instructions,
        output_modalities=['audio'],
        audio=AudioConfiguration(
            input=AudioInput(
                transcription=InputAudioTranscription(model=settings.openai_transcription_model),
                noise_reduction=InputAudioNoiseReduction(type='far_field'),
                turn_detection=SemanticTurnDetection(
                    eagerness='low',
                    create_response=None,
                    interrupt_response=True,
                ),
            ),
            output=AudioOutput(
                voice=settings.openai_voice,
                speed=settings.openai_tts_speed,
            ),
        ),
        tracing='auto',
    )

    llm = OpenAIRealtimeLLMService(
        api_key=settings.openai_api_key,
        settings=OpenAIRealtimeLLMService.Settings(
            model=settings.openai_realtime_model,
            session_properties=session_properties,
        ),
    )

    context_aggregator = create_context_aggregator(
        instructions or settings.agent_instructions,
        greeting or settings.agent_greeting,
    )
    if on_transcript is not None:
        attach_transcript_handlers(context_aggregator, on_transcript)

    pipeline = Pipeline([
        transport.input(),
        context_aggregator.user(),
        llm,
        transport.output(),
        context_aggregator.assistant(),
    ])
    return pipeline, llm
