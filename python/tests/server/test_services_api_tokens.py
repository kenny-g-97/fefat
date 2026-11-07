"""The API tokens of step 4.2 (D-86): each shown once and kept as its SHA-256 alone, its name
unique, a revoked one refused, and its last use written at most once a minute."""

import hashlib
import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from fefat_app.container import Container
from fefat_app.database.models import ApiTokenRow
from fefat_app.services.api_tokens import NoSuchApiTokenError
from fefat_app.services.identity import ApiTokenIdentity
from local_server import STARTED_AT, SettableClock, database_bytes


def last_used(engine: Engine) -> list[datetime | None]:
    with Session(engine) as session:
        return list(session.scalars(select(ApiTokenRow.last_used_at)).all())


def test_an_api_token_identifies_its_name_and_lands_on_disk_as_its_hash_alone(
    container: Container, engine: Engine
) -> None:
    token = container.api_tokens.create("notebook")

    identity = container.api_tokens.identity_of_token(token)

    with Session(engine) as session:
        token_hashes = session.scalars(select(ApiTokenRow.token_hash)).all()
    assert token.startswith("fefat_")
    assert identity == ApiTokenIdentity(token_name="notebook")
    assert token_hashes == [hashlib.sha256(token.encode()).hexdigest()]
    assert token.encode() not in database_bytes()


def test_a_token_name_in_use_is_refused(container: Container) -> None:
    container.api_tokens.create("notebook")
    expected = "Expected a new token name, got 'notebook', which a token has."

    with pytest.raises(ValueError, match=re.escape(expected)):
        container.api_tokens.create("notebook")


@pytest.mark.parametrize("name", ["", "two words", "x" * 65, "naïve"])
def test_a_token_name_outside_the_pattern_is_refused(container: Container, name: str) -> None:
    with pytest.raises(ValueError, match="Expected a token name of 1 to 64 letters, digits"):
        container.api_tokens.create(name)


def test_a_revoked_or_unknown_token_has_no_identity(container: Container, engine: Engine) -> None:
    token = container.api_tokens.create("notebook")
    with Session(engine) as session, session.begin():
        session.execute(update(ApiTokenRow).values(revoked_at=STARTED_AT))

    assert container.api_tokens.identity_of_token(token) is None
    assert container.api_tokens.identity_of_token("fefat_unknown") is None


def test_a_token_is_marked_used_at_most_once_a_minute(
    container: Container, clock: SettableClock, engine: Engine
) -> None:
    token = container.api_tokens.create("notebook")
    assert last_used(engine) == [None]

    container.api_tokens.identity_of_token(token)
    clock.advance(timedelta(seconds=59))
    container.api_tokens.identity_of_token(token)
    assert last_used(engine) == [STARTED_AT]
    clock.advance(timedelta(seconds=1))
    container.api_tokens.identity_of_token(token)
    assert last_used(engine) == [STARTED_AT + timedelta(minutes=1)]


def test_a_revoked_token_leaves_the_live_tokens_and_is_refused(container: Container) -> None:
    token = container.api_tokens.create("notebook")
    container.api_tokens.create("script")

    container.api_tokens.revoke("notebook")

    assert [live.name for live in container.api_tokens.live_tokens()] == ["script"]
    assert container.api_tokens.identity_of_token(token) is None


def test_only_a_live_token_can_be_revoked(container: Container) -> None:
    container.api_tokens.create("notebook")
    container.api_tokens.revoke("notebook")
    expected = "Expected the name of a live API token, got 'notebook'."

    with pytest.raises(NoSuchApiTokenError, match=re.escape(expected)):
        container.api_tokens.revoke("notebook")
    with pytest.raises(NoSuchApiTokenError):
        container.api_tokens.revoke("never-made")
