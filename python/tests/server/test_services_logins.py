"""The password, the logins, and the login sessions of step 4.2 (D-86, `01-architecture.md`
section 8), over the access records in the database: the password kept as its Argon2 hash and a
session as its token's SHA-256, five attempts a minute counted before the password is checked,
sessions of 30 days, and a new password ending every session."""

import hashlib
import os
import re
import sqlite3
import time
from datetime import datetime, timedelta

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from fefat.config import resolve_paths
from fefat_app.container import Container
from fefat_app.database.models import LoginSessionRow, SettingRow
from fefat_app.services.logins import TooManyLoginAttemptsError, WrongPasswordError
from local_server import PASSWORD, STARTED_AT, SettableClock, database_bytes


def logged_in(container: Container) -> str:
    """The token of a new login session with the password set."""
    container.logins.set_password(PASSWORD)
    return container.logins.login(PASSWORD).token.get_secret_value()


def last_seen(engine: Engine) -> list[datetime]:
    with Session(engine) as session:
        return list(session.scalars(select(LoginSessionRow.last_seen_at)).all())


def test_a_login_with_the_password_opens_a_session_its_token_identifies(
    container: Container,
) -> None:
    container.logins.set_password(PASSWORD)

    opened = container.logins.login(PASSWORD)

    token = opened.token.get_secret_value()
    csrf_token = hashlib.sha256(f"fefat-csrf:{token}".encode()).hexdigest()
    assert container.logins.identity_of_session(token) == opened.identity
    assert opened.identity.expires_at == STARTED_AT + timedelta(days=30)
    assert opened.identity.csrf_token == csrf_token


def test_the_password_and_the_session_land_on_disk_as_hashes_alone(
    container: Container, engine: Engine
) -> None:
    token = logged_in(container)

    with Session(engine) as session:
        setting = session.get(SettingRow, "password_hash")
        token_hashes = session.scalars(select(LoginSessionRow.token_hash)).all()
    kept = database_bytes()

    assert setting is not None
    assert str(setting.value_json).startswith("$argon2id$")
    assert token_hashes == [hashlib.sha256(token.encode()).hexdigest()]
    assert PASSWORD.encode() not in kept
    assert token.encode() not in kept


def test_a_wrong_password_and_a_login_before_any_password_are_refused(
    container: Container,
) -> None:
    with pytest.raises(WrongPasswordError):
        container.logins.login(PASSWORD)
    container.logins.set_password(PASSWORD)

    with pytest.raises(WrongPasswordError, match="Expected the password that was set, got another"):
        container.logins.login("another password")


@pytest.mark.parametrize("length", [7, 1025])
def test_a_password_too_short_or_too_long_is_refused(container: Container, length: int) -> None:
    expected = f"Expected a password of 8 to 1024 characters, got {length}."

    with pytest.raises(ValueError, match=re.escape(expected)):
        container.logins.set_password("x" * length)

    assert not container.logins.password_is_set()


def test_a_sixth_attempt_in_a_minute_is_refused_before_its_password_is_checked(
    container: Container, clock: SettableClock
) -> None:
    container.logins.set_password(PASSWORD)
    for _ in range(5):
        with pytest.raises(WrongPasswordError):
            container.logins.login("another password")
        clock.advance(timedelta(seconds=5))

    with pytest.raises(TooManyLoginAttemptsError, match="try again in 35 seconds") as refused:
        container.logins.login(PASSWORD)

    assert refused.value.retry_after_seconds == 35
    clock.advance(timedelta(seconds=35))
    assert container.logins.login(PASSWORD).identity.kind == "session"


def test_a_login_that_succeeds_clears_the_count(container: Container) -> None:
    container.logins.set_password(PASSWORD)
    for _ in range(4):
        with pytest.raises(WrongPasswordError):
            container.logins.login("another password")
    container.logins.login(PASSWORD)

    for _ in range(4):
        with pytest.raises(WrongPasswordError):
            container.logins.login("another password")


def test_a_session_ends_after_thirty_days(container: Container, clock: SettableClock) -> None:
    token = logged_in(container)

    clock.advance(timedelta(days=30) - timedelta(microseconds=1))
    assert container.logins.identity_of_session(token) is not None
    clock.advance(timedelta(microseconds=1))
    assert container.logins.identity_of_session(token) is None


def test_the_next_login_removes_the_sessions_that_ended(
    container: Container, clock: SettableClock, engine: Engine
) -> None:
    logged_in(container)
    clock.advance(timedelta(days=31))

    container.logins.login(PASSWORD)

    assert last_seen(engine) == [STARTED_AT + timedelta(days=31)]


def test_a_session_is_marked_seen_at_most_once_a_minute(
    container: Container, clock: SettableClock, engine: Engine
) -> None:
    token = logged_in(container)

    clock.advance(timedelta(seconds=59))
    container.logins.identity_of_session(token)
    assert last_seen(engine) == [STARTED_AT]
    clock.advance(timedelta(seconds=1))
    container.logins.identity_of_session(token)
    assert last_seen(engine) == [STARTED_AT + timedelta(minutes=1)]


def test_a_new_password_ends_every_session(container: Container) -> None:
    token = logged_in(container)

    container.logins.set_password("another password")

    assert container.logins.identity_of_session(token) is None
    with pytest.raises(WrongPasswordError):
        container.logins.login(PASSWORD)
    assert container.logins.login("another password").identity.kind == "session"


def test_logout_ends_the_session_and_an_unknown_token_has_no_identity(
    container: Container,
) -> None:
    token = logged_in(container)

    container.logins.logout(token)
    container.logins.logout(token)

    assert container.logins.identity_of_session(token) is None
    assert container.logins.identity_of_session("not a token") is None


def test_a_request_is_identified_while_another_writer_holds_the_database(
    container: Container,
) -> None:
    # A read begins deferred, so a command or a job writing at the time holds up no request.
    session_token = logged_in(container)
    api_token = container.api_tokens.create("notebook")
    container.api_tokens.identity_of_token(api_token)
    writer = sqlite3.connect(resolve_paths(os.environ).database_file, timeout=0)
    writer.execute("BEGIN IMMEDIATE")

    try:
        started = time.perf_counter()
        session = container.logins.identity_of_session(session_token)
        token = container.api_tokens.identity_of_token(api_token)
        waited = time.perf_counter() - started
    finally:
        writer.rollback()
        writer.close()

    assert (session is not None, token is not None) == (True, True)
    assert waited < 1


def test_a_last_seen_time_due_while_another_writer_holds_the_database_waits_for_later(
    container: Container, clock: SettableClock, engine: Engine
) -> None:
    # The write of a last-seen time is bookkeeping: a busy database skips it, after SQLite's
    # busy timeout, rather than failing the request.
    session_token = logged_in(container)
    clock.advance(timedelta(minutes=1))
    writer = sqlite3.connect(resolve_paths(os.environ).database_file, timeout=0)
    writer.execute("BEGIN IMMEDIATE")

    try:
        session = container.logins.identity_of_session(session_token)
    finally:
        writer.rollback()
        writer.close()

    assert session is not None
    assert last_seen(engine) == [STARTED_AT]
    container.logins.identity_of_session(session_token)
    assert last_seen(engine) == [STARTED_AT + timedelta(minutes=1)]


def test_a_password_hash_argon2_cannot_read_is_refused_with_the_remedy(
    container: Container, engine: Engine
) -> None:
    container.logins.set_password(PASSWORD)
    with Session(engine) as session, session.begin():
        session.execute(update(SettingRow).values(value_json="not a hash"))

    with pytest.raises(ValueError, match="run `fefat password set`"):
        container.logins.login(PASSWORD)
