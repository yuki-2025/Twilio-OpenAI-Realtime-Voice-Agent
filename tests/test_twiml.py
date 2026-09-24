from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app import main
from tests.conftest import make_settings


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(main, 'settings', make_settings(public_base_url='https://example.ngrok-free.app'))
    return TestClient(main.app)


def test_inbound_twiml_is_unchanged(client):
    response = client.post('/twiml')

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/xml')
    assert response.text == (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Response>\n'
        '  <Connect>\n'
        '    <Stream url="wss://example.ngrok-free.app/twilio/dev-session" />\n'
        '  </Connect>\n'
        '</Response>'
    )


def test_outbound_twiml_streams_to_same_websocket_with_direction_parameter(client):
    response = client.post('/twiml/outbound')

    assert response.status_code == 200
    assert response.headers['content-type'].startswith('application/xml')
    stream = ET.fromstring(response.text).find('./Connect/Stream')
    assert stream is not None
    assert stream.get('url') == 'wss://example.ngrok-free.app/twilio/dev-session'
    params = {p.get('name'): p.get('value') for p in stream.findall('Parameter')}
    assert params == {'direction': 'outbound'}
