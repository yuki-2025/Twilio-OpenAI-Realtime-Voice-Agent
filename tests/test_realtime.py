"""Turn-taking behaviour of the context aggregator used with OpenAI Realtime.

OpenAI Realtime runs its own server-side VAD: it interrupts the bot itself on
`input_audio_buffer.speech_started`, and it delivers the caller's transcript only
*after* it has already started replying. The user aggregator must therefore never
treat a transcript as a barge-in, or it cuts off every bot reply ~1s after it starts.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    InterimTranscriptionFrame,
    InterruptionFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.tests.utils import SleepFrame, run_test

from app.realtime import create_context_aggregator

TS = '2026-09-24T00:00:00Z'


async def test_late_realtime_transcript_does_not_interrupt_bot_reply():
    aggregator = create_context_aggregator('SYSTEM', 'HELLO')

    # Frames arrive from the LLM side (upstream), in the order seen in the call logs:
    # the bot reply has started, then the caller's transcript streams in.
    down, up = await run_test(
        aggregator.user(),
        frames_to_send=[
            BotStartedSpeakingFrame(),
            InterimTranscriptionFrame('hel', '', TS),
            TranscriptionFrame('hello there', '', TS),
            SleepFrame(0.3),
        ],
        frames_to_send_direction=FrameDirection.UPSTREAM,
    )

    emitted = [type(frame) for frame in (*down, *up)]
    assert InterruptionFrame not in emitted
    assert UserStartedSpeakingFrame not in emitted


async def test_caller_turn_signalled_by_realtime_service_is_added_to_context():
    aggregator = create_context_aggregator('SYSTEM', 'HELLO')

    await run_test(
        aggregator.user(),
        frames_to_send=[
            UserStartedSpeakingFrame(),
            UserStoppedSpeakingFrame(),
            TranscriptionFrame('hello there', '', TS),
            SleepFrame(0.5),
        ],
        frames_to_send_direction=FrameDirection.UPSTREAM,
    )

    assert aggregator.user().context.get_messages()[-1] == {'role': 'user', 'content': 'hello there'}
