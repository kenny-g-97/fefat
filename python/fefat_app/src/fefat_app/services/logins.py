"""The password and the login sessions of the local server (steps 4.2 and 4.3, D-86,
`01-architecture.md` section 8): the password is set at `fefat up`'s first run or by `fefat
password set`, or changed on the settings page with the current one, and kept as its Argon2
hash; a login checks it, at most five attempts a minute, and opens a session of 30 days whose
token the cookie carries; a new password ends every session."""

import math
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from pydantic import BaseModel, ConfigDict, SecretStr

from fefat_app.ports import AccessRecords, Clock
from fefat_app.services.identity import (
    SEEN_EVERY,
    SessionIdentity,
    csrf_token,
    new_token,
    token_hash,
)

SESSION_LIFETIME = timedelta(days=30)
MINIMUM_PASSWORD_LENGTH = 8
MAXIMUM_PASSWORD_LENGTH = 1024
ATTEMPTS_PER_WINDOW = 5
ATTEMPT_WINDOW = timedelta(minutes=1)


class WrongPasswordError(Exception):
    """A login with another password than the one set, or before one is set."""

    def __init__(self) -> None:
        super().__init__("Expected the password that was set, got another.")


class TooManyLoginAttemptsError(Exception):
    """A login after five attempts in the last minute, refused before its password is checked."""

    def __init__(self, retry_after: timedelta) -> None:
        self.retry_after_seconds = max(1, math.ceil(retry_after.total_seconds()))
        super().__init__(
            f"Expected at most {ATTEMPTS_PER_WINDOW} login attempts a minute, got more: try "
            f"again in {self.retry_after_seconds} seconds."
        )


class OpenedLoginSession(BaseModel):
    """A login that succeeded: the token for the session's cookie, and the identity of the
    session's requests."""

    model_config = ConfigDict(frozen=True)

    token: SecretStr
    identity: SessionIdentity


class LoginAttempts:
    """The login's rate limit, a counter in the server's memory (D-86): at most five attempts in
    any minute, each counted before its password is checked, so that simultaneous logins cannot
    each run an Argon2 hash; a refused attempt is not counted, and a login that succeeds clears
    the count. The server's request threads share it, hence the lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._recent: tuple[datetime, ...] = ()

    def admit(self, now: datetime) -> None:
        """Count an attempt made at `now`, refused where five were counted in the minute before."""
        with self._lock:
            recent = tuple(attempt for attempt in self._recent if now - attempt < ATTEMPT_WINDOW)
            if len(recent) >= ATTEMPTS_PER_WINDOW:
                self._recent = recent
                raise TooManyLoginAttemptsError(retry_after=min(recent) + ATTEMPT_WINDOW - now)
            self._recent = (*recent, now)

    def clear(self) -> None:
        """Forget the attempts counted so far."""
        with self._lock:
            self._recent = ()


@dataclass(frozen=True)
class Logins:
    """The password, the logins, and the login sessions, over the access records."""

    records: AccessRecords
    hasher: PasswordHasher
    attempts: LoginAttempts
    clock: Clock

    def password_is_set(self) -> bool:
        """Whether a password was set, which `fefat up` asks for on its first run."""
        return self.records.password_hash() is not None

    def set_password(self, password: str) -> None:
        """Keep `password`'s Argon2 hash as the password, which ends every login session; one
        of fewer than 8 or more than 1,024 characters is refused."""
        if not MINIMUM_PASSWORD_LENGTH <= len(password) <= MAXIMUM_PASSWORD_LENGTH:
            raise ValueError(
                f"Expected a password of {MINIMUM_PASSWORD_LENGTH} to {MAXIMUM_PASSWORD_LENGTH} "
                f"characters, got {len(password)}."
            )
        self.records.replace_password_hash(self.hasher.hash(password))

    def login(self, password: str) -> OpenedLoginSession:
        """A new login session when `password` is the password; refused with `WrongPasswordError`,
        or with `TooManyLoginAttemptsError` before the password is checked."""
        now = self.clock()
        self._check(password, now)
        self.records.remove_expired_sessions(now)
        return self._opened_session(now)

    def change_password(self, current: str, new: str) -> OpenedLoginSession:
        """Keep `new` as the password once `current` is checked, as a login is, against the same
        five attempts a minute; every login session ends, and the new one returned keeps the
        browser that asked logged in. Refused with `WrongPasswordError`, with
        `TooManyLoginAttemptsError`, or, for a new password of the wrong length, `ValueError`."""
        now = self.clock()
        self._check(current, now)
        self.set_password(new)
        return self._opened_session(now)

    def identity_of_session(self, token: str) -> SessionIdentity | None:
        """The identity of the login session whose cookie carries `token`, or None where there
        is no such session or it has ended."""
        hashed = token_hash(token)
        session = self.records.session_by_hash(hashed)
        now = self.clock()
        if session is None or session.expires_at <= now:
            return None
        if now - session.last_seen_at >= SEEN_EVERY:
            self.records.mark_session_seen(hashed, now)
        return SessionIdentity(expires_at=session.expires_at, csrf_token=csrf_token(token))

    def logout(self, token: str) -> None:
        """End the login session whose cookie carries `token`, if it has not ended."""
        self.records.remove_session(token_hash(token))

    def _check(self, password: str, now: datetime) -> None:
        self.attempts.admit(now)
        if not self._is_the_password(password):
            raise WrongPasswordError()
        self.attempts.clear()

    def _opened_session(self, now: datetime) -> OpenedLoginSession:
        token = new_token()
        expires_at = now + SESSION_LIFETIME
        self.records.add_session(token_hash(token), created_at=now, expires_at=expires_at)
        identity = SessionIdentity(expires_at=expires_at, csrf_token=csrf_token(token))
        return OpenedLoginSession(token=SecretStr(token), identity=identity)

    def _is_the_password(self, password: str) -> bool:
        stored = self.records.password_hash()
        if stored is None:
            return False
        try:
            return self.hasher.verify(stored, password)
        except VerifyMismatchError:
            return False
        except InvalidHashError as unreadable:
            raise ValueError(
                "Expected the password's Argon2 hash in the settings table, got one argon2 "
                "cannot read: run `fefat password set`."
            ) from unreadable
