"""Turn-taking and transcript capture of the context aggregators used with OpenAI Realtime.

The real OpenAIRealtimeLLMService is replaced by a scripted stand-in that emits the
same frames, in the same directions, as pipecat 1.11's service does:

- server VAD speech start/stop -> Proposed{Started,Stopped}SpeakingFrame, broadcast
- caller transcript            -> (Interim)TranscriptionFrame, upstream, often *after*
                                  the agent reply has started
- agent reply                  -> LLMFullResponseStart / TTSText... / LLMFullResponseEnd,
                                  downstream

Everything else (both aggregators, turn strategies, realtime mode) is real.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    DataFrame,
    Frame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    ProposedUserStartedSpeakingFrame,
    ProposedUserStoppedSpeakingFrame,
    TranscriptionFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.tests.utils import SleepFrame, run_test
from pipecat.utils.text.base_text_aggregator import AggregationType

from app.realtime import attach_transcript_handlers, create_context_aggregator

TS = '2026-09-24T18:00:00.000Z'
UP = FrameDirection.UPSTREAM
DOWN = FrameDirection.DOWNSTREAM
START_TIMEOUT = 10.0  # first pipeline start in a cold process can exceed run_test's 1s default


@dataclass
class EmitFrame(DataFrame):
    """Instruction for the fake service: push `frame` in `direction`."""

    frame: Frame | None = None
    direction: FrameDirection = DOWN


class FakeRealtimeService(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, EmitFrame):
            await self.push_frame(frame.frame, frame.direction)
        else:
            await self.push_frame(frame, direction)


def emit(frame: Frame, direction: FrameDirection) -> EmitFrame:
    return EmitFrame(frame=frame, direction=direction)


def broadcast(frame_cls: type[Frame]) -> list[EmitFrame]:
    return [emit(frame_cls(), DOWN), emit(frame_cls(), UP)]


def agent_reply_start() -> list[EmitFrame]:
    return [emit(LLMFullResponseStartFrame(), DOWN), emit(TTSStartedFrame(), DOWN), emit(BotStartedSpeakingFrame(), UP)]


def agent_says(text: str) -> list[EmitFrame]:
    llm_text = LLMTextFrame(text)
    llm_text.append_to_context = False
    tts_text = TTSTextFrame(text, aggregated_by=AggregationType.SENTENCE)
    tts_text.includes_inter_frame_spaces = True
    return [emit(llm_text, DOWN), emit(tts_text, DOWN)]


def agent_reply_end() -> list[EmitFrame]:
    return [emit(TTSStoppedFrame(), DOWN), emit(LLMFullResponseEndFrame(), DOWN)]


async def run_call(frames: list[Frame]):
    pair = create_context_aggregator('SYSTEM', 'HELLO')
    transcripts: list[tuple[str, str, str]] = []

    async def on_transcript(role: str, text: str, timestamp: str) -> None:
        transcripts.append((role, text, timestamp))

    attach_transcript_handlers(pair, on_transcript)
    down, up = await run_test(
        Pipeline([pair.user(), FakeRealtimeService(), pair.assistant()]),
        frames_to_send=frames,
        start_timeout=START_TIMEOUT,
    )
    return [type(f) for f in (*down, *up)], transcripts


# --- turn-taking -----------------------------------------------------------


async def test_late_caller_transcript_does_not_interrupt_agent_reply():
    emitted, _ = await run_call([
        *agent_reply_start(),
        emit(InterimTranscriptionFrame('hel', '', TS), UP),
        emit(TranscriptionFrame('hello there', '', TS), UP),
        SleepFrame(0.3),
    ])

    assert InterruptionFrame not in emitted
    assert UserStartedSpeakingFrame not in emitted


async def test_caller_speech_detected_by_realtime_service_interrupts_agent():
    emitted, _ = await run_call([
        *agent_reply_start(),
        *agent_says('Let me tell you about'),
        *broadcast(ProposedUserStartedSpeakingFrame),
        SleepFrame(0.3),
    ])

    assert InterruptionFrame in emitted
    assert UserStartedSpeakingFrame in emitted


# --- transcript capture ----------------------------------------------------


async def test_both_sides_of_a_turn_reach_the_transcript_callback_in_order():
    _, transcripts = await run_call([
        *broadcast(ProposedUserStartedSpeakingFrame),
        SleepFrame(0.05),
        *broadcast(ProposedUserStoppedSpeakingFrame),
        *agent_reply_start(),
        *agent_says('Sure, where'),
        *agent_says(' are  you\nflying?'),
        # the caller transcript lands after the agent reply has started
        emit(TranscriptionFrame('I want to book a flight', '', TS), UP),
        SleepFrame(0.1),
        *agent_reply_end(),
        SleepFrame(0.3),
    ])

    assert [(role, text) for role, text, _ in transcripts] == [
        ('user', 'I want to book a flight'),
        ('agent', 'Sure, where are you flying?'),
    ]
    for _, _, timestamp in transcripts:
        assert datetime.fromisoformat(timestamp).tzinfo is not None


async def test_agent_turn_without_any_text_is_not_reported():
    _, transcripts = await run_call([
        *agent_reply_start(),
        *agent_reply_end(),
        SleepFrame(0.3),
    ])

    assert transcripts == []
