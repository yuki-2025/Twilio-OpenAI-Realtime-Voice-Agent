"""Decide which parts of the app outside clients may reach.

Behind ngrok or Render the client address cannot tell local from remote, so a request
counts as external when it carries X-Forwarded-For (both proxies add it) or its Host
header is not a loopback name. External requests may only reach the endpoints Twilio
needs, plus the call console when it is password protected (console_path); everything
else gets 403, or close code 1008 for WebSockets.
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


def is_public_path(path: str, console_path: str | None = None) -> bool:
    if console_path and (path == console_path or path.startswith(console_path + '/')):
        return True
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


class LocalOnlyGuard:
    def __init__(self, app: ASGIApp, console_path: str | None = None) -> None:
        self.app = app
        self.console_path = console_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope['type'] in ('http', 'websocket')
            and is_external(scope)
            and not is_public_path(scope['path'], self.console_path)
        ):
            if scope['type'] == 'http':
                await PlainTextResponse('Forbidden', status_code=403)(scope, receive, send)
            else:
                await send({'type': 'websocket.close', 'code': POLICY_VIOLATION})
            return
        await self.app(scope, receive, send)
