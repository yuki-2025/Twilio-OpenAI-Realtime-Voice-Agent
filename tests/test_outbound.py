from __future__ import annotations

import pytest
from twilio.rest import Client

from app import outbound
from app.outbound import OutboundConfigError, make_call
from tests.conftest import (
    TEST_ACCOUNT_SID,
    TEST_AUTH_TOKEN,
    RecordingHttpClient,
    call_resource,
    make_settings,
)

CALLS_URI = f'https://api.twilio.com/2010-04-01/Accounts/{TEST_ACCOUNT_SID}/Calls.json'


def twilio_client(http: RecordingHttpClient) -> Client:
    return Client(TEST_ACCOUNT_SID, TEST_AUTH_TOKEN, http_client=http)


def ok_http(sid: str = 'CA1234567890abcdef1234567890abcdef') -> RecordingHttpClient:
    return RecordingHttpClient(201, call_resource(sid, '+15555550199', '+15555550100'))


# --- make_call -------------------------------------------------------------


def test_make_call_sends_to_from_and_outbound_twiml_url(settings):
    http = ok_http('CAaaaabbbbccccddddeeeeffff00001111')

    sid = make_call('+15555550199', settings, client=twilio_client(http))

    assert sid == 'CAaaaabbbbccccddddeeeeffff00001111'
    assert len(http.requests) == 1
    request = http.requests[0]
    assert request['method'] == 'POST'
    assert request['uri'] == CALLS_URI
    assert request['data'] == {
        'To': '+15555550199',
        'From': '+15555550100',
        'Url': 'https://example.ngrok-free.app/twiml/outbound',
        'Method': 'POST',
    }


def test_make_call_strips_trailing_slash_from_public_base_url():
    http = ok_http()
    settings = make_settings(public_base_url='https://example.ngrok-free.app/')

    make_call('+15555550199', settings, client=twilio_client(http))

    assert http.requests[0]['data']['Url'] == 'https://example.ngrok-free.app/twiml/outbound'


@pytest.mark.parametrize(
    'bad_number',
    [
        '5555550199',  # missing +country code
        '+1 555 555 0199',  # spaces
        '+1-555-555-0199',  # dashes
        '+05555550199',  # country code cannot start with 0
        '+1555555019912345',  # 16 digits, longer than E.164 allows
        '',
    ],
)
def test_make_call_rejects_non_e164_number_without_calling_twilio(settings, bad_number):
    http = ok_http()

    with pytest.raises(OutboundConfigError):
        make_call(bad_number, settings, client=twilio_client(http))

    assert http.requests == []


@pytest.mark.parametrize(
    'missing',
    ['twilio_account_sid', 'twilio_auth_token', 'twilio_phone_number', 'public_base_url'],
)
def test_make_call_requires_each_setting_without_calling_twilio(missing):
    http = ok_http()
    settings = make_settings(**{missing: ''})

    with pytest.raises(OutboundConfigError, match=missing.upper()):
        make_call('+15555550199', settings, client=twilio_client(http))

    assert http.requests == []


# --- CLI -------------------------------------------------------------------


@pytest.fixture
def cli_http(monkeypatch, settings) -> RecordingHttpClient:
    """Point the CLI at test settings and a real SDK client whose network layer is recorded."""
    http = ok_http('CAcli0000000000000000000000000000')
    monkeypatch.setattr(outbound, 'get_settings', lambda: settings)
    monkeypatch.setattr(outbound, 'Client', lambda sid, token: Client(sid, token, http_client=http))
    return http


def test_cli_dry_run_prints_call_parameters_and_places_no_call(cli_http, capsys):
    exit_code = outbound.main(['+15555550199', '--dry-run'])

    out = capsys.readouterr().out
    assert exit_code == 0
    assert '+15555550199' in out
    assert '+15555550100' in out
    assert 'https://example.ngrok-free.app/twiml/outbound' in out
    assert cli_http.requests == []


def test_cli_places_call_and_prints_call_sid(cli_http, capsys):
    exit_code = outbound.main(['+15555550199'])

    assert exit_code == 0
    assert len(cli_http.requests) == 1
    assert cli_http.requests[0]['data']['To'] == '+15555550199'
    assert 'CAcli0000000000000000000000000000' in capsys.readouterr().out


def test_cli_returns_2_on_invalid_number(cli_http, capsys):
    exit_code = outbound.main(['5555550199'])

    assert exit_code == 2
    assert cli_http.requests == []
    assert capsys.readouterr().err != ''


def test_cli_returns_1_when_twilio_rejects_the_call(monkeypatch, settings, capsys):
    http = RecordingHttpClient(
        400,
        {
            'code': 21215,
            'message': 'Geo Permission configuration is not permitting call',
            'more_info': 'https://www.twilio.com/docs/errors/21215',
            'status': 400,
        },
    )
    monkeypatch.setattr(outbound, 'get_settings', lambda: settings)
    monkeypatch.setattr(outbound, 'Client', lambda sid, token: Client(sid, token, http_client=http))

    exit_code = outbound.main(['+15555550199'])

    assert exit_code == 1
    assert '21215' in capsys.readouterr().err
