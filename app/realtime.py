from __future__ import annotations

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
from pipecat.turns.user_turn_strategies import ExternalUserTurnStrategies

from app.config import Settings


def create_context_aggregator(instructions: str, greeting: str) -> LLMContextAggregatorPair:
    context = LLMContext(
        messages=[
            {'role': 'system', 'content': instructions},
            {'role': 'user', 'content': f'Say to the caller: "{greeting}"'},
        ]
    )
    # OpenAI Realtime detects turns server-side and interrupts the bot itself on speech_started.
    # Pipecat's default local strategies treat the caller transcript (which arrives after the
    # bot has started replying) as a barge-in and cut every reply short, so defer to the service.
    return LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(user_turn_strategies=ExternalUserTurnStrategies()),
    )


def create_realtime_pipeline(transport, settings: Settings, instructions: str | None = None, greeting: str | None = None):
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

    pipeline = Pipeline([
        transport.input(),
        context_aggregator.user(),
        llm,
        transport.output(),
        context_aggregator.assistant(),
    ])
    return pipeline, llm
