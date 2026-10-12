from __future__ import annotations

import json
import logging

import pytest
from twilio.http import HttpClient
from twilio.http.response import Response
from twilio.rest import Client

from app import outbound
from app.outbound import OutboundConfigError, hang_up_all, make_call
from tests.conftest import (
    TEST_ACCOUNT_SID,
    TEST_AUTH_TOKEN,
    TEST_FROM_NUMBER,
    RecordingHttpClient,
    call_resource,
    make_settings,
)

CALLS_URI = f'https://api.twilio.com/2010-04-01/Accounts/{TEST_ACCOUNT_SID}/Calls.json'
CALLER = '+15555550199'
OTHER_NUMBER = '+15555550142'


def twilio_client(http: HttpClient) -> Client:
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
    'bad_url',
    [
        'http://127.0.0.1:8000/ui/',  # loopback, plain http and a path
        'http://example.ngrok-free.app',  # Twilio media streams need wss://, so https://
        'https://localhost:8000',
        'https://127.0.0.1:8000',
        'https://[::1]:8000',
        'https://192.168.1.20:8000',  # LAN address, unreachable from Twilio
        'https://example.ngrok-free.app/ui',  # /twiml/outbound would land under /ui
        'example.ngrok-free.app',  # no scheme
    ],
)
def test_make_call_rejects_public_base_url_twilio_cannot_reach_without_calling(bad_url):
    http = ok_http()

    with pytest.raises(OutboundConfigError, match='PUBLIC_BASE_URL'):
        make_call('+15555550199', make_settings(public_base_url=bad_url), client=twilio_client(http))

    assert http.requests == []


@pytest.mark.parametrize('good_url', ['https://example.ngrok-free.app', 'https://twilio-voice-agent.onrender.com/'])
def test_make_call_accepts_public_https_base_url(good_url):
    http = ok_http()

    make_call('+15555550199', make_settings(public_base_url=good_url), client=twilio_client(http))

    assert len(http.requests) == 1


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


# --- hang_up_all -----------------------------------------------------------


class FakeCallsApi(HttpClient):
    """Twilio Calls API over a fixed set of calls: GET filters by Status/From/To, POST updates one call."""

    def __init__(self, calls: list[dict[str, object]], rejected: frozenset[str] = frozenset()) -> None:
        super().__init__(logger=logging.getLogger('twilio.http_client.test'), is_async=False)
        self.calls = calls
        self.rejected = rejected
        self.updates: list[tuple[str, dict[str, object]]] = []

    def request(self, method, uri, params=None, data=None, headers=None, auth=None, timeout=None, allow_redirects=False):
        if method == 'GET':
            params = dict(params or {})
            matches = [
                call
                for call in self.calls
                if call['status'] == params.get('Status')
                and call['from'] == params.get('From', call['from'])
                and call['to'] == params.get('To', call['to'])
            ]
            return Response(200, json.dumps({'calls': matches, 'next_page_uri': None, 'page': 0, 'page_size': 50}))
        sid = uri.rsplit('/', 1)[-1].removesuffix('.json')
        self.updates.append((sid, dict(data or {})))
        if sid in self.rejected:
            body = {'code': 21220, 'message': 'Call is not in-progress. Cannot redirect.', 'status': 400}
            return Response(400, json.dumps(body))
        return Response(200, json.dumps(active_call(sid, 'completed', CALLER, TEST_FROM_NUMBER)))


def active_call(sid: str, status: str, from_: str, to: str) -> dict[str, object]:
    return {**call_resource(sid, to, from_), 'status': status}


def test_hang_up_all_ends_every_active_call_on_our_number_only(settings):
    api = FakeCallsApi(
        [
            active_call('CAinbound', 'in-progress', CALLER, TEST_FROM_NUMBER),
            active_call('CAringing', 'ringing', TEST_FROM_NUMBER, CALLER),
            active_call('CAqueued', 'queued', TEST_FROM_NUMBER, OTHER_NUMBER),
            active_call('CAdone', 'completed', TEST_FROM_NUMBER, CALLER),
            active_call('CAsomeoneelse', 'in-progress', OTHER_NUMBER, CALLER),
        ]
    )

    report = hang_up_all(settings, client=twilio_client(api))

    assert sorted(report.ended) == ['CAinbound', 'CAqueued', 'CAringing']
    assert report.failed == ()
    assert sorted(api.updates) == [(sid, {'Status': 'completed'}) for sid in ['CAinbound', 'CAqueued', 'CAringing']]


def test_hang_up_all_ends_a_call_listed_twice_only_once(settings):
    api = FakeCallsApi([active_call('CAself', 'in-progress', TEST_FROM_NUMBER, TEST_FROM_NUMBER)])

    report = hang_up_all(settings, client=twilio_client(api))

    assert report.ended == ('CAself',)
    assert [sid for sid, _ in api.updates] == ['CAself']


def test_hang_up_all_keeps_going_when_a_call_cannot_be_ended(settings):
    api = FakeCallsApi(
        [
            active_call('CAstuck', 'in-progress', CALLER, TEST_FROM_NUMBER),
            active_call('CAok', 'in-progress', TEST_FROM_NUMBER, CALLER),
        ],
        rejected=frozenset({'CAstuck'}),
    )

    report = hang_up_all(settings, client=twilio_client(api))

    assert report.ended == ('CAok',)
    [(sid, reason)] = report.failed
    assert sid == 'CAstuck' and '21220' in reason


def test_hang_up_all_with_no_active_calls_updates_nothing(settings):
    api = FakeCallsApi([active_call('CAdone', 'completed', CALLER, TEST_FROM_NUMBER)])

    report = hang_up_all(settings, client=twilio_client(api))

    assert (report.ended, report.failed, api.updates) == ((), (), [])


def test_hang_up_all_does_not_need_public_base_url():
    api = FakeCallsApi([active_call('CAinbound', 'in-progress', CALLER, TEST_FROM_NUMBER)])

    report = hang_up_all(make_settings(public_base_url=''), client=twilio_client(api))

    assert report.ended == ('CAinbound',)


@pytest.mark.parametrize('missing', ['twilio_account_sid', 'twilio_auth_token', 'twilio_phone_number'])
def test_hang_up_all_requires_twilio_settings_without_calling_twilio(missing):
    api = FakeCallsApi([active_call('CAinbound', 'in-progress', CALLER, TEST_FROM_NUMBER)])

    with pytest.raises(OutboundConfigError, match=missing.upper()):
        hang_up_all(make_settings(**{missing: ''}), client=twilio_client(api))

    assert api.updates == []


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
