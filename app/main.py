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


@app.post('/twiml')
async def twiml(_: Request) -> PlainTextResponse:
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="{settings.websocket_url}" />
  </Connect>
</Response>'''
    return PlainTextResponse(xml, media_type='application/xml')


@app.websocket('/twilio/{session_id}')
async def twilio_websocket(websocket: WebSocket, session_id: str) -> None:
    await handle_twilio_websocket(websocket, session_id, settings)
