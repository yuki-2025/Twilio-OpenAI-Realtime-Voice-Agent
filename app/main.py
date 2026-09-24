from __future__ import annotations

import structlog
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.twilio_handler import handle_twilio_websocket

logger = structlog.get_logger(__name__)
settings = get_settings()
app = FastAPI(title=settings.app_name)


@app.get('/health')
async def health() -> dict[str, str]:
    return {'status': 'ok'}


def build_twiml(stream_url: str, direction: str | None = None) -> str:
    """Return TwiML that connects the call to our media-stream WebSocket.

    When direction is set it is sent as a <Parameter>, which Twilio forwards in the
    stream 'start' message so the WebSocket handler can tell outbound from inbound calls.
    """
    if direction is None:
        stream = f'<Stream url="{stream_url}" />'
    else:
        stream = (
            f'<Stream url="{stream_url}">\n'
            f'      <Parameter name="direction" value="{direction}" />\n'
            f'    </Stream>'
        )
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    {stream}
  </Connect>
</Response>'''


@app.post('/twiml')
async def twiml(_: Request) -> PlainTextResponse:
    return PlainTextResponse(build_twiml(settings.websocket_url), media_type='application/xml')


@app.post('/twiml/outbound')
async def twiml_outbound(_: Request) -> PlainTextResponse:
    return PlainTextResponse(build_twiml(settings.websocket_url, 'outbound'), media_type='application/xml')


@app.websocket('/twilio/{session_id}')
async def twilio_websocket(websocket: WebSocket, session_id: str) -> None:
    await handle_twilio_websocket(websocket, session_id, settings)
