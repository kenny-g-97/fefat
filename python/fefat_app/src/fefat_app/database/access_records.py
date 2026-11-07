"""The access records over the app's database (step 4.2, D-86): the password's Argon2 hash as the
`settings` row `password_hash`, and the `sessions` and `api_tokens` tables, each token kept by
its SHA-256 alone (`fefat_app.ports.AccessRecords`). Each call is a transaction of its own; the
reads begin deferred (`fefat_app.database.schema.reading`), and the last-seen and last-used
times, which are bookkeeping, are skipped when another writer holds the database."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Engine, delete, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from fefat_app.database.models import ApiTokenRow, LoginSessionRow, SettingRow
from fefat_app.database.schema import not_waiting, reading
from fefat_app.ports import ApiToken, LoginSession, TokenNameInUseError

PASSWORD_HASH_KEY = "password_hash"
"""The `settings` row that keeps the password's hash."""
PRIMARY_CODE = 0xFF
"""The bits of an SQLite error code that name its primary error."""


@dataclass(frozen=True)
class AccessTables:
    """`AccessRecords` in the tables of `engine`'s database."""

    engine: Engine

    def password_hash(self) -> str | None:
        with Session(reading(self.engine)) as session:
            row = session.get(SettingRow, PASSWORD_HASH_KEY)
            if row is None:
                return None
            kept: object = row.value_json
        if not isinstance(kept, str):
            raise ValueError(
                f"Expected the password's hash as text in the settings row {PASSWORD_HASH_KEY}, "
                f"got {type(kept).__name__}."
            )
        return kept

    def replace_password_hash(self, password_hash: str) -> None:
        with Session(self.engine) as session, session.begin():
            row = session.get(SettingRow, PASSWORD_HASH_KEY)
            if row is None:
                session.add(SettingRow(key=PASSWORD_HASH_KEY, value_json=password_hash))
            else:
                row.value_json = password_hash
            session.execute(delete(LoginSessionRow))

    def add_session(self, token_hash: str, created_at: datetime, expires_at: datetime) -> None:
        with Session(self.engine) as session, session.begin():
            session.add(
                LoginSessionRow(
                    token_hash=token_hash,
                    created_at=created_at,
                    expires_at=expires_at,
                    last_seen_at=created_at,
                )
            )

    def session_by_hash(self, token_hash: str) -> LoginSession | None:
        with Session(reading(self.engine)) as session:
            row = session.scalars(
                select(LoginSessionRow).where(LoginSessionRow.token_hash == token_hash)
            ).one_or_none()
            if row is None:
                return None
            return LoginSession(expires_at=row.expires_at, last_seen_at=row.last_seen_at)

    def mark_session_seen(self, token_hash: str, seen_at: datetime) -> None:
        with _skipped_when_busy(), Session(not_waiting(self.engine)) as session, session.begin():
            session.execute(
                update(LoginSessionRow)
                .where(LoginSessionRow.token_hash == token_hash)
                .values(last_seen_at=seen_at)
            )

    def remove_session(self, token_hash: str) -> None:
        with Session(self.engine) as session, session.begin():
            session.execute(delete(LoginSessionRow).where(LoginSessionRow.token_hash == token_hash))

    def remove_expired_sessions(self, now: datetime) -> None:
        with Session(self.engine) as session, session.begin():
            session.execute(delete(LoginSessionRow).where(LoginSessionRow.expires_at <= now))

    def add_api_token(self, name: str, token_hash: str, created_at: datetime) -> None:
        with Session(self.engine) as session, session.begin():
            used = session.scalars(select(ApiTokenRow.id).where(ApiTokenRow.name == name)).first()
            if used is not None:
                raise TokenNameInUseError(name)
            session.add(ApiTokenRow(name=name, token_hash=token_hash, created_at=created_at))

    def api_token_by_hash(self, token_hash: str) -> ApiToken | None:
        with Session(reading(self.engine)) as session:
            row = session.scalars(
                select(ApiTokenRow).where(
                    ApiTokenRow.token_hash == token_hash, ApiTokenRow.revoked_at.is_(None)
                )
            ).one_or_none()
            return None if row is None else _api_token(row)

    def live_api_tokens(self) -> tuple[ApiToken, ...]:
        with Session(reading(self.engine)) as session:
            rows = session.scalars(
                select(ApiTokenRow)
                .where(ApiTokenRow.revoked_at.is_(None))
                .order_by(ApiTokenRow.created_at, ApiTokenRow.name)
            )
            return tuple(_api_token(row) for row in rows)

    def revoke_api_token(self, name: str, revoked_at: datetime) -> bool:
        with Session(self.engine) as session, session.begin():
            row = session.scalars(
                select(ApiTokenRow).where(
                    ApiTokenRow.name == name, ApiTokenRow.revoked_at.is_(None)
                )
            ).one_or_none()
            if row is None:
                return False
            row.revoked_at = revoked_at
            return True

    def mark_api_token_used(self, token_hash: str, used_at: datetime) -> None:
        with _skipped_when_busy(), Session(not_waiting(self.engine)) as session, session.begin():
            session.execute(
                update(ApiTokenRow)
                .where(ApiTokenRow.token_hash == token_hash)
                .values(last_used_at=used_at)
            )


def _api_token(row: ApiTokenRow) -> ApiToken:
    return ApiToken(name=row.name, created_at=row.created_at, last_used_at=row.last_used_at)


@contextmanager
def _skipped_when_busy() -> Generator[None]:
    """A write that the next request makes again, given up rather than failing the request
    when another writer holds the database, which `not_waiting` refuses at once; SQLite's busy
    error is its primary code, under the extended ones such as `SQLITE_BUSY_SNAPSHOT`."""
    try:
        yield
    except OperationalError as refused:
        locked = refused.orig
        if not isinstance(locked, sqlite3.OperationalError):
            raise
        if locked.sqlite_errorcode & PRIMARY_CODE != sqlite3.SQLITE_BUSY:
            raise
