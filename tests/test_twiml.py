from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app import main
from tests.conftest import make_settings

STREAM_URL = 'wss://example.ngrok-free.app/twilio/dev-session'


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main, 'settings', make_settings(public_base_url='https://example.ngrok-free.app'))
    return TestClient(main.app)


def stream_of(response) -> tuple[str | None, dict[str, str | None]]:
    """Return the <Stream> url and its <Parameter> name/value pairs."""
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/xml')
    stream = ET.fromstring(response.text).find('./Connect/Stream')
    assert stream is not None
    return stream.get('url'), {p.get('name'): p.get('value') for p in stream.findall('Parameter')}


def test_inbound_twiml_passes_direction_and_caller_number(client):
    response = client.post('/twiml', data={'CallSid': 'CA1', 'From': '+15555550199', 'To': '+15555550100'})

    assert stream_of(response) == (STREAM_URL, {'direction': 'inbound', 'remote': '+15555550199'})


def test_outbound_twiml_passes_direction_and_callee_number(client):
    response = client.post('/twiml/outbound', data={'CallSid': 'CA2', 'From': '+15555550100', 'To': '+15555550199'})

    assert stream_of(response) == (STREAM_URL, {'direction': 'outbound', 'remote': '+15555550199'})


def test_twiml_escapes_parameter_values(client):
    response = client.post('/twiml', data={'From': '"><Hangup/>&'})

    _, params = stream_of(response)
    assert params['remote'] == '"><Hangup/>&'
    assert ET.fromstring(response.text).find('.//Hangup') is None


@pytest.mark.parametrize(('path', 'direction'), [('/twiml', 'inbound'), ('/twiml/outbound', 'outbound')])
def test_twiml_without_form_fields_omits_remote_number(client, path, direction):
    response = client.post(path)

    assert stream_of(response) == (STREAM_URL, {'direction': direction})
