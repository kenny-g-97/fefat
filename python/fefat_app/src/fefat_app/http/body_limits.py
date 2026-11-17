"""The largest request body each route reads (steps 4.2 and 5.12, D-93): the import wizard's upload
takes `config.toml`'s `upload_megabytes`, and every other route 1 MiB, each refused with 413 past
it before it is held in memory, as Starlette's `RequestBodyLimitResponder` refuses it, whether the
body declares its length or comes in chunks."""

from starlette.middleware.body_limit import RequestBodyLimitResponder
from starlette.types import ASGIApp, Receive, Scope, Send

from fefat_app.container import Container

BODY_BYTES = 1024 * 1024
"""The largest request body a route other than the upload's reads."""
MEBIBYTE = 1024 * 1024


class BodyLimits:
    """The body limit of each request to `app`: the settings' upload limit for a `POST` to
    `upload_path` exactly, else `BODY_BYTES`."""

    def __init__(self, app: ASGIApp, upload_path: str) -> None:
        self.app = app
        self.upload_path = upload_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        await RequestBodyLimitResponder(self.app, self._limit(scope))(scope, receive, send)

    def _limit(self, scope: Scope) -> int:
        if scope["method"] != "POST" or scope["path"] != self.upload_path:
            return BODY_BYTES
        container: Container = scope["app"].state.container
        return container.settings.upload_megabytes * MEBIBYTE
