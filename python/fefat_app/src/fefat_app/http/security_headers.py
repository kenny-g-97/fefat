"""The headers every response carries (`01-architecture.md` section 8, D-86): the content
security policy, which lets a page load nothing from elsewhere, images only from the app or from
data and blob URLs, and styles from the app or written into the page, while its scripts stay the
app's own files, unless a route sets its own, as the API's docs do; `nosniff`, a same-origin
referrer, no framing; and under `/v1/`, no caching.

It wraps the whole app, outside Starlette's handler of failures, so that a 500 carries them too;
a plain ASGI class, which never buffers a body."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from fefat_app.http.api_prefix import is_api_path

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'"
)
"""Section 8's policy: nothing from elsewhere, no remote image in the agent's chat, and from
step 5.4 the style elements that Radix's overlays and Lightweight Charts write, scripts staying
`'self'` alone (D-93); a nonce for each page waits in `BACKLOG.md`."""
SECURITY_HEADERS = (
    ("Content-Security-Policy", CONTENT_SECURITY_POLICY),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "same-origin"),
    ("X-Frame-Options", "DENY"),
)
API_HEADERS = (("Cache-Control", "no-store"),)
"""What an answer of the API adds: it may hold a secret's state or a CSRF token."""


class SecurityHeaders:
    """Adds the security headers to each HTTP response of the app it wraps, where the response
    does not set them itself."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        added = SECURITY_HEADERS + (API_HEADERS if is_api_path(path) else ())

        async def send_with_the_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in added:
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_the_headers)
