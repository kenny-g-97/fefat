"""The local server's parts on each test's own home (step 4.2): the database of its `FEFAT_HOME`,
made and migrated; a clock the test moves; keyring in memory; Argon2 at its lowest cost, so that
many logins take no time, while the server keeps argon2-cffi's defaults; a client of the app;
and the server's log."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from fefat.config import Settings, resolve_paths
from fefat_app.container import Container
from fefat_app.credentials import KeyringCredentialStore
from fefat_app.database.access_records import AccessTables
from fefat_app.database.schema import opened_database, upgrade_schema
from fefat_app.http.app import create_app
from fefat_app.http.server_log import configure_server_log
from fefat_app.services.api_tokens import ApiTokenIssuer
from fefat_app.services.logins import LoginAttempts, Logins
from local_server import LOOPBACK, STARTED_AT, SettableClock
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


@pytest.fixture
def client(container: Container) -> Iterator[TestClient]:
    """A client of the app over `container`, without a built web app, at the loopback."""
    with TestClient(create_app(container, built_web_app=None), base_url=LOOPBACK) as opened:
        yield opened


@pytest.fixture
def server_log(root_log_put_back: None, tmp_path: Path) -> Path:
    """The server's log file, configured as `fefat up` configures it, and put back after."""
    return configure_server_log(tmp_path / "logs")
