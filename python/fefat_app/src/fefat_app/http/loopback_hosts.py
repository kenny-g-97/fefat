"""The host check (step 4.2, D-86, `01-architecture.md` section 8): a request or a WebSocket whose
`Host` is not 127.0.0.1 or localhost, in any case and at any port, is refused, a request with a
problem and a WebSocket closed before it opens, so that a page of another site whose DNS name
was pointed at 127.0.0.1 reaches nothing of the server. A plain ASGI class inside the request
ids, so that the problem carries its request's id."""

from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from fefat_app.http.problems import problem_response

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost"})
POLICY_VIOLATION = 1008
"""The close code of a WebSocket refused by a policy (RFC 6455)."""


class LoopbackHosts:
    """Refuses each request and WebSocket of the app it wraps that names another host."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        host, _, _ = Headers(scope=scope).get("host", "").lower().partition(":")
        if host in LOOPBACK_HOSTS:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": POLICY_VIOLATION})
            return
        detail = f"Expected the host 127.0.0.1 or localhost, got {host!r}."
        refused = problem_response(Request(scope), 400, detail)
        await refused(scope, receive, send)
