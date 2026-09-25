from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from twilio.base.exceptions import TwilioRestException

from app.call_events import CallEvent, CallEventHub
from app.outbound import OutboundConfigError
from app.ui import Row, dial, format_event
from tests.conftest import make_settings

CDT = timezone(timedelta(hours=-5))
AT_18_00_05_UTC = datetime(2026, 9, 24, 18, 0, 5, tzinfo=UTC)


def make_event(**overrides) -> CallEvent:
    values = dict(
        kind='transcript',
        call_sid='CA123',
        timestamp=AT_18_00_05_UTC,
        direction='outbound',
        remote_number='+15555550199',
        role='user',
        text='hello there',
    )
    values.update(overrides)
    return CallEvent(**values)


# --- format_event ------------------------------------------------------------


def test_transcript_row_shows_local_time_direction_speaker_and_text():
    assert format_event(make_event(), tz=CDT) == Row(
        time='13:00:05',
        direction='↗',
        remote='+15555550199',
        speaker='User',
        text='hello there',
        is_status=False,
    )


def test_agent_line_on_inbound_call():
    row = format_event(make_event(direction='inbound', role='agent', text='Hi!'), tz=CDT)

    assert (row.direction, row.speaker, row.text) == ('↙', 'Agent', 'Hi!')


@pytest.mark.parametrize(
    ('overrides', 'text'),
    [
        ({'kind': 'dialing', 'role': None, 'text': ''}, 'Dialing… (CA123)'),
        ({'kind': 'call_started', 'role': None, 'text': ''}, 'Call started'),
        ({'kind': 'call_ended', 'role': None, 'text': '', 'duration_sec': 78.4}, 'Call ended (78s)'),
        ({'kind': 'call_ended', 'role': None, 'text': ''}, 'Call ended'),
    ],
)
def test_status_rows(overrides, text):
    row = format_event(make_event(**overrides), tz=CDT)

    assert (row.speaker, row.text, row.is_status) == ('', text, True)


# --- dial --------------------------------------------------------------------


class RecordingDialer:
    def __init__(self, result: str | Exception = 'CAnew') -> None:
        self.result = result
        self.calls: list[tuple[str, object]] = []

    def __call__(self, to, settings):
        self.calls.append((to, settings))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_dial_places_call_and_announces_it_on_the_hub():
    hub, dialer, settings = CallEventHub(), RecordingDialer('CAnew'), make_settings()

    result = await dial('  +15555550199 ', settings, hub=hub, place_call=dialer)

    assert result.ok and result.call_sid == 'CAnew'
    assert dialer.calls == [('+15555550199', settings)]
    [event] = hub.history()
    assert (event.kind, event.call_sid, event.direction, event.remote_number) == (
        'dialing',
        'CAnew',
        'outbound',
        '+15555550199',
    )


@pytest.mark.parametrize('bad', ['5555550199', '+1 555 555 0199', ''])
async def test_dial_rejects_invalid_number_without_calling(bad):
    hub, dialer = CallEventHub(), RecordingDialer()

    result = await dial(bad, make_settings(), hub=hub, place_call=dialer)

    assert not result.ok
    assert dialer.calls == []
    assert hub.history() == []


@pytest.mark.parametrize(
    ('error', 'expected_in_message'),
    [
        (TwilioRestException(400, 'https://api.twilio.com/x', msg='Geo permission denied', code=21215), '21215'),
        (OutboundConfigError('Missing required setting(s) in .env: TWILIO_PHONE_NUMBER'), 'TWILIO_PHONE_NUMBER'),
    ],
)
async def test_dial_reports_failures_instead_of_raising(error, expected_in_message):
    hub = CallEventHub()

    result = await dial('+15555550199', make_settings(), hub=hub, place_call=RecordingDialer(error))

    assert not result.ok
    assert expected_in_message in result.message
    assert hub.history() == []
