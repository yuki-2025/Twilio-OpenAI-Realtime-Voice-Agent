"""Keep the call console private while Twilio's endpoints stay public through ngrok.

ngrok forwards to localhost, so the client address cannot tell local from remote.
Instead a request counts as external when it carries X-Forwarded-For (ngrok adds it)
or its Host header is not a loopback name. External requests may only reach the
endpoints Twilio needs; everything else, including the console UI and its
WebSocket, gets 403 / close code 1008.
"""

from __future__ import annotations

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

PUBLIC_PATHS = frozenset({'/health', '/twiml', '/twiml/outbound'})
PUBLIC_PREFIXES = ('/twilio/',)
LOOPBACK_HOSTS = frozenset({'localhost', '127.0.0.1', '::1'})
POLICY_VIOLATION = 1008


def _host_name(host_header: str) -> str:
    if host_header.startswith('['):  # IPv6 literal, e.g. [::1]:8000
        return host_header[1 : host_header.find(']')]
    return host_header.split(':', 1)[0]


def is_external(scope: Scope) -> bool:
    headers = dict(scope.get('headers') or [])
    if b'x-forwarded-for' in headers:
        return True
    host = headers.get(b'host', b'').decode('latin-1').lower()
    return _host_name(host) not in LOOPBACK_HOSTS


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


class LocalOnlyGuard:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] in ('http', 'websocket') and is_external(scope) and not is_public_path(scope['path']):
            if scope['type'] == 'http':
                await PlainTextResponse('Forbidden', status_code=403)(scope, receive, send)
            else:
                await send({'type': 'websocket.close', 'code': POLICY_VIOLATION})
            return
        await self.app(scope, receive, send)
