"""The local server's parts on each test's own home (step 4.2): the database of its `FEFAT_HOME`,
made and migrated; a clock the test moves; keyring in memory; and Argon2 at its lowest cost, so
that many logins take no time, while the server keeps argon2-cffi's defaults."""

import os
from collections.abc import Iterator

import pytest
from argon2 import PasswordHasher
from sqlalchemy import Engine

from fefat.config import Settings, resolve_paths
from fefat_app.container import Container
from fefat_app.credentials import KeyringCredentialStore
from fefat_app.database.access_records import AccessTables
from fefat_app.database.schema import opened_database, upgrade_schema
from fefat_app.services.api_tokens import ApiTokenIssuer
from fefat_app.services.logins import LoginAttempts, Logins
from local_server import STARTED_AT, SettableClock
from memory_keyring import MemoryKeyring


@pytest.fixture
def clock() -> SettableClock:
    return SettableClock(STARTED_AT)


@pytest.fixture
def engine() -> Iterator[Engine]:
    """The database of the test's `FEFAT_HOME`, made and migrated."""
    with opened_database(resolve_paths(os.environ).database_file) as opened:
        upgrade_schema(opened)
        yield opened


@pytest.fixture
def keyring_backend() -> MemoryKeyring:
    return MemoryKeyring()


@pytest.fixture
def container(engine: Engine, clock: SettableClock, keyring_backend: MemoryKeyring) -> Container:
    """The server's container as `build_container` wires it, but for the clock, keyring, and
    Argon2's cost."""
    records = AccessTables(engine)
    cheap_hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    return Container(
        settings=Settings(),
        credentials=KeyringCredentialStore(keyring_backend),
        logins=Logins(records, cheap_hasher, LoginAttempts(), clock),
        api_tokens=ApiTokenIssuer(records, clock),
    )
