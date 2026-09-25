from __future__ import annotations

import pytest

from app.twilio_handler import resolve_greeting


@pytest.mark.parametrize(
    ('call_body', 'expected'),
    [
        ({'direction': 'outbound'}, 'OUTBOUND GREETING'),
        ({'direction': 'inbound'}, 'INBOUND GREETING'),
        ({}, 'INBOUND GREETING'),
    ],
)
def test_resolve_greeting_picks_greeting_by_call_direction(settings, call_body, expected):
    assert resolve_greeting(call_body, settings) == expected


async def test_call_runner_leaves_ctrl_c_to_uvicorn():
    # On Windows pipecat installs SIGINT via signal.signal and never restores it, so after
    # one call Ctrl+C would only cancel pipelines instead of stopping the server.
    import signal

    from pipecat.frames.frames import EndFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineWorker

    from app.twilio_handler import create_call_runner

    before = signal.getsignal(signal.SIGINT)
    worker = PipelineWorker(Pipeline([]), enable_rtvi=False, idle_timeout_secs=None)
    await worker.queue_frame(EndFrame())

    runner = create_call_runner()
    await runner.add_workers(worker)
    await runner.run()

    assert signal.getsignal(signal.SIGINT) is before
