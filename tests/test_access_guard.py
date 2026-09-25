from __future__ import annotations

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main
from app.access_guard import LocalOnlyGuard
from tests.conftest import make_settings

VIA_NGROK = {'host': 'example.ngrok-free.app', 'x-forwarded-for': '203.0.113.7'}
LOCAL = {'host': 'localhost:8000'}


def guarded_app() -> FastAPI:
    app = FastAPI()

    @app.get('/health')
    async def health():
        return {'ok': True}

    @app.post('/twiml')
    async def twiml():
        return {'ok': True}

    @app.get('/ui/')
    async def console():
        return {'ok': True}

    @app.websocket('/twilio/{session_id}')
    async def media(ws: WebSocket, session_id: str):
        await ws.accept()
        await ws.send_text('media')
        await ws.close()

    @app.websocket('/ui/_nicegui_ws/socket.io/')
    async def ui_socket(ws: WebSocket):
        await ws.accept()
        await ws.send_text('ui')
        await ws.close()

    app.add_middleware(LocalOnlyGuard)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(guarded_app())


def test_console_is_forbidden_through_ngrok(client):
    assert client.get('/ui/', headers=dict(VIA_NGROK)).status_code == 403


@pytest.mark.parametrize(
    'headers',
    [
        {'host': 'example.ngrok-free.app'},  # public Host header alone
        {'host': 'localhost:8000', 'x-forwarded-for': '203.0.113.7'},  # proxied with a spoofed local Host
        {'host': '192.168.1.20:8000'},  # another machine on the LAN
    ],
)
def test_console_is_forbidden_for_any_non_local_request(client, headers):
    assert client.get('/ui/', headers=headers).status_code == 403


@pytest.mark.parametrize('host', ['localhost:8000', '127.0.0.1:8000', '[::1]:8000', 'localhost'])
def test_console_is_allowed_from_this_machine(client, host):
    assert client.get('/ui/', headers={'host': host}).status_code == 200


def test_twilio_http_endpoints_stay_reachable_through_ngrok(client):
    assert client.get('/health', headers=dict(VIA_NGROK)).status_code == 200
    assert client.post('/twiml', headers=dict(VIA_NGROK)).status_code == 200


def test_twilio_media_websocket_stays_reachable_through_ngrok(client):
    with client.websocket_connect('/twilio/dev-session', headers=dict(VIA_NGROK)) as ws:
        assert ws.receive_text() == 'media'


def test_console_websocket_is_rejected_through_ngrok(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect('/ui/_nicegui_ws/socket.io/', headers=dict(VIA_NGROK)) as ws:
            ws.receive_text()
    assert exc_info.value.code == 1008


def test_real_app_blocks_console_but_serves_twiml_through_ngrok(monkeypatch):
    monkeypatch.setattr(main, 'settings', make_settings())
    client = TestClient(main.app)

    assert client.get('/ui', headers=dict(VIA_NGROK)).status_code == 403
    assert client.post('/twiml/outbound', headers=dict(VIA_NGROK)).status_code == 200
