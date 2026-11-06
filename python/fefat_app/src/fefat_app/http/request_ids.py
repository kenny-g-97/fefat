"""The id of every request (step 4.2, D-86): 16 hexadecimal digits made as the request arrives,
kept in its scope's state for the problem it may end in, echoed in `X-Request-Id`, and logged
with its method, path, status, and duration in the server's log under `FefatPaths.logs_dir`, the
path quoted, so that a newline it carries cannot write a line of its own
(`fefat_app.http.server_log`); a failure is logged under the id by the kind of error alone,
since uvicorn logs its traceback right after.

It wraps the whole app, outside Starlette's handler of failures, so that a 500 carries the id
too; a plain ASGI class, which never buffers a body, as step 4.4's streams need."""

import logging
import secrets
import time

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-Id"
REQUEST_ID_BYTES = 8
logger = logging.getLogger("fefat_app.http")


class RequestIds:
    """Gives each HTTP request of the app it wraps an id, and logs the request under it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = secrets.token_hex(REQUEST_ID_BYTES)
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status = 500

        async def send_with_the_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        line = f"request_id={request_id} method={scope['method']} path={scope['path']!r}"
        try:
            await self.app(scope, receive, send_with_the_id)
        except Exception as failure:
            logger.error("%s failed with %s", line, type(failure).__name__)
            raise
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            logger.info("%s status=%d duration_ms=%.1f", line, status, elapsed)
