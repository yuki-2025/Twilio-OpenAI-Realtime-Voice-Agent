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
