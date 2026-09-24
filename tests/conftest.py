from __future__ import annotations

import json
import logging

import pytest
from twilio.http import HttpClient
from twilio.http.response import Response

from app.config import Settings

TEST_ACCOUNT_SID = 'AC' + '0' * 32
TEST_AUTH_TOKEN = 'test-auth-token'
TEST_FROM_NUMBER = '+15555550100'
TEST_BASE_URL = 'https://example.ngrok-free.app'


def make_settings(**overrides: object) -> Settings:
    """Build Settings without reading the developer's real .env file."""
    values: dict[str, object] = {
        'twilio_account_sid': TEST_ACCOUNT_SID,
        'twilio_auth_token': TEST_AUTH_TOKEN,
        'twilio_phone_number': TEST_FROM_NUMBER,
        'public_base_url': TEST_BASE_URL,
        'agent_greeting': 'INBOUND GREETING',
        'agent_outbound_greeting': 'OUTBOUND GREETING',
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def call_resource(sid: str, to: str, from_: str) -> dict[str, object]:
    """Shape of the JSON body Twilio returns for POST /Calls.json (201 Created)."""
    return {
        'sid': sid,
        'account_sid': TEST_ACCOUNT_SID,
        'to': to,
        'to_formatted': to,
        'from': from_,
        'from_formatted': from_,
        'status': 'queued',
        'direction': 'outbound-api',
        'api_version': '2010-04-01',
        'date_created': None,
        'date_updated': None,
        'start_time': None,
        'end_time': None,
        'duration': None,
        'price': None,
        'price_unit': 'USD',
        'answered_by': None,
        'caller_name': None,
        'forwarded_from': None,
        'group_sid': None,
        'parent_call_sid': None,
        'phone_number_sid': 'PN' + '0' * 32,
        'queue_time': '0',
        'trunk_sid': None,
        'annotation': None,
        'uri': f'/2010-04-01/Accounts/{TEST_ACCOUNT_SID}/Calls/{sid}.json',
        'subresource_uris': {},
    }


class RecordingHttpClient(HttpClient):
    """Replaces only the network layer of the real Twilio SDK and records each request."""

    def __init__(self, status_code: int, body: dict[str, object]) -> None:
        super().__init__(logger=logging.getLogger('twilio.http_client.test'), is_async=False)
        self.status_code = status_code
        self.body = body
        self.requests: list[dict[str, object]] = []

    def request(self, method, uri, params=None, data=None, headers=None, auth=None, timeout=None, allow_redirects=False):
        self.requests.append({'method': method, 'uri': uri, 'data': dict(data or {}), 'auth': auth})
        return Response(self.status_code, json.dumps(self.body))


@pytest.fixture
def settings() -> Settings:
    return make_settings()
