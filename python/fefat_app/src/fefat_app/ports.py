"""The app's seams (`01-architecture.md` section 10, `08-code-design.md` section 1, D-27): each a
`typing.Protocol` that an adapter implements, built once in `fefat_app.container` and passed to
what uses it, so that swapping an adapter is a module of its own and a line of the container.

The credential store is the first (step 4.1), and the records of who may use the local server
the second (step 4.2); the executor, the dispatcher, the blob store, the agent's runtime, and
the licence arrive with the steps that first use them."""

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

type Clock = Callable[[], datetime]
"""Now, as an aware instant in UTC: the system's clock in the server, a settable one in tests."""


class SecretName(StrEnum):
    """The secrets FEFAT keeps, each the key of a service it calls: the agent's model provider
    (Phase 8) and a market data vendor (D-37). The list is closed, since a credential store
    cannot list what it holds; a step that calls another service adds its name."""

    ANTHROPIC = "anthropic"
    DATABENTO = "databento"


class CredentialStore(Protocol):
    """Where the secrets live: the operating system's credential store, never `config.toml` or
    another file FEFAT writes (`01-architecture.md` section 8)."""

    def get(self, name: SecretName) -> str | None:
        """The secret `name`, or None where none is stored."""
        ...

    def set(self, name: SecretName, value: str) -> None:
        """Store `value` as the secret `name`, in place of any stored before; an empty value is
        refused."""
        ...

    def delete(self, name: SecretName) -> None:
        """Remove the secret `name`, refused where none is stored."""
        ...


class LoginSession(BaseModel):
    """A login session of the local server: when it ends and when it was last seen. The token
    its cookie carries is kept only as its SHA-256, which names it."""

    model_config = ConfigDict(frozen=True)

    expires_at: AwareDatetime
    last_seen_at: AwareDatetime


class ApiToken(BaseModel):
    """An API token of a notebook or a script, by its name, kept only as its SHA-256, which
    names it, with when it was last used."""

    model_config = ConfigDict(frozen=True)

    name: str
    last_used_at: AwareDatetime | None


class AccessRecords(Protocol):
    """What lets a client into the local server (step 4.2, D-86): the password's Argon2 hash,
    the login sessions, and the API tokens, each token known by its SHA-256 alone, so that the
    records hold nothing a client could present."""

    def password_hash(self) -> str | None:
        """The password's Argon2 hash, or None before a password is set."""
        ...

    def replace_password_hash(self, password_hash: str) -> None:
        """Keep `password_hash` as the password's, in place of any before, and end every login
        session in the same transaction."""
        ...

    def add_session(self, token_hash: str, created_at: datetime, expires_at: datetime) -> None:
        """Begin a login session for the token of SHA-256 `token_hash`, last seen when made."""
        ...

    def session_by_hash(self, token_hash: str) -> LoginSession | None:
        """The login session of the token of SHA-256 `token_hash`, or None."""
        ...

    def mark_session_seen(self, token_hash: str, seen_at: datetime) -> None:
        """Record that the login session of the token of SHA-256 `token_hash` was seen, or give
        it up while another writer holds the records, the next request recording it."""
        ...

    def remove_session(self, token_hash: str) -> None:
        """End the login session of the token of SHA-256 `token_hash`, if there is one."""
        ...

    def remove_expired_sessions(self, now: datetime) -> None:
        """End every login session whose end is not after `now`."""
        ...

    def add_api_token(self, name: str, token_hash: str, created_at: datetime) -> None:
        """Keep the API token of SHA-256 `token_hash` under `name`; a name in use is refused."""
        ...

    def api_token_by_hash(self, token_hash: str) -> ApiToken | None:
        """The API token of SHA-256 `token_hash`, or None, which a revoked token gives too."""
        ...

    def mark_api_token_used(self, token_hash: str, used_at: datetime) -> None:
        """Record that the API token of SHA-256 `token_hash` was used, or give it up while
        another writer holds the records, the next request recording it."""
        ...
