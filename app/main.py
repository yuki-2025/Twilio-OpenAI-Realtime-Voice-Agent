from __future__ import annotations

from xml.sax.saxutils import quoteattr

import structlog
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import PlainTextResponse
from nicegui import ui

from app.access_guard import LocalOnlyGuard
from app.config import get_settings
from app.twilio_handler import handle_twilio_websocket
from app.ui import register_console

logger = structlog.get_logger(__name__)
settings = get_settings()
app = FastAPI(title=settings.app_name)


@app.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok'}


def build_twiml(stream_url: str, params: dict[str, str]) -> str:
    """Return TwiML that connects the call to our media-stream WebSocket.

    Each param becomes a <Parameter>, which Twilio forwards in the stream 'start'
    message so the WebSocket handler knows the call direction and remote number.
    """
    lines = [f'      <Parameter name={quoteattr(name)} value={quoteattr(value)} />' for name, value in params.items()]
    body = '\n'.join(lines)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url={quoteattr(stream_url)}>
{body}
    </Stream>
  </Connect>
</Response>'''


async def _twiml_response(request: Request, direction: str, remote_field: str) -> PlainTextResponse:
    # Twilio posts call details as a form: From/To are the caller/callee numbers.
    form = await request.form()
    params = {'direction': direction}
    remote = form.get(remote_field)
    if isinstance(remote, str) and remote:
        params['remote'] = remote
    return PlainTextResponse(build_twiml(settings.websocket_url, params), media_type='application/xml')


@app.post('/twiml')
async def twiml(request: Request) -> PlainTextResponse:
    return await _twiml_response(request, 'inbound', 'From')


@app.post('/twiml/outbound')
async def twiml_outbound(request: Request) -> PlainTextResponse:
    return await _twiml_response(request, 'outbound', 'To')


@app.websocket('/twilio/{session_id}')
async def twilio_websocket(websocket: WebSocket, session_id: str) -> None:
    await handle_twilio_websocket(websocket, session_id, settings)


# Call console at http://localhost:8000/ui. It shares this process (and the call event hub)
# with the voice pipeline, so run uvicorn with a single worker.
register_console(settings)
ui.run_with(app, mount_path='/ui', title='Voice Agent Console', show_welcome_message=False)

# ngrok exposes this whole app; only Twilio's endpoints may be reached from outside.
app.add_middleware(LocalOnlyGuard)
