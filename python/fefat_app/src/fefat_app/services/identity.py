"""Who a request comes from (step 4.2, D-86): a login session, the browser's, or an API token, a
notebook's or a script's; and the tokens that prove it, each 32 random bytes kept only as its
SHA-256, so that the database holds nothing a client could present (`01-architecture.md`
section 8)."""

import hashlib
import secrets
from datetime import timedelta
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

TOKEN_BYTES = 32
"""The random bytes of a session's or an API token's token."""
SEEN_EVERY = timedelta(minutes=1)
"""How stale a session's last-seen or a token's last-used time may grow before a request writes
it again, so that most requests write nothing."""
CSRF_PREFIX = "fefat-csrf:"
"""What a session's token is hashed under to give its CSRF token, which is never its own hash."""


class SessionIdentity(BaseModel):
    """A request of a login session, with the CSRF token that every state-changing request the
    session's cookie authenticates must carry in `X-CSRF-Token`, and when the session ends."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["session"] = "session"
    expires_at: AwareDatetime
    csrf_token: str


class ApiTokenIdentity(BaseModel):
    """A request of an API token, by the token's name; it needs no CSRF token, since a browser
    never sends a bearer token by itself."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["api_token"] = "api_token"
    token_name: str


Identity = Annotated[SessionIdentity | ApiTokenIdentity, Field(discriminator="kind")]
"""Either identity, told apart by its `kind`."""


def new_token() -> str:
    """A fresh token of `TOKEN_BYTES` random bytes, URL-safe."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> str:
    """The SHA-256 a token is kept and found by."""
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(session_token: str) -> str:
    """The CSRF token of a login session, derived from its token and kept nowhere."""
    return hashlib.sha256((CSRF_PREFIX + session_token).encode()).hexdigest()
