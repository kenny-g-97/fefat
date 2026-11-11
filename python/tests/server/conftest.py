"""The local server's parts on each test's own home (step 4.2): the database of its `FEFAT_HOME`,
made and migrated; a clock the test moves; keyring in memory; Argon2 at its lowest cost, so that
many logins take no time, while the server keeps argon2-cffi's defaults; a client of the app;
the server's log; the executors, cold and warm (step 4.5); the data catalog over the store of
its `FEFAT_DATA_DIR` (step 5.1); and the library's strategies and features over their index
(step 5.2)."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from fefat.config import Settings, resolve_paths
from fefat.market.store import Store
from fefat_app.container import Container
from fefat_app.credentials import KeyringCredentialStore
from fefat_app.database.access_records import AccessTables
from fefat_app.database.job_records import JobTables
from fefat_app.database.library_index import LibraryTables
from fefat_app.database.preferences import PreferenceRows
from fefat_app.database.schema import opened_database, upgrade_schema
from fefat_app.executor.subprocess_executor import SubprocessExecutor
from fefat_app.http.app import create_app
from fefat_app.http.server_log import configure_server_log
from fefat_app.jobs.dispatcher import LocalDispatcher
from fefat_app.jobs.worker import JobTimings
from fefat_app.services.api_tokens import ApiTokenIssuer
from fefat_app.services.catalog import MarketCatalog
from fefat_app.services.features import SavedFeatures
from fefat_app.services.jobs import Jobs
from fefat_app.services.logins import LoginAttempts, Logins
from fefat_app.services.strategies import SavedStrategies
from local_server import LOOPBACK, STARTED_AT, SettableClock, running_runners
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
def job_records(engine: Engine) -> JobTables:
    """The jobs and their events in the test's database (step 4.4)."""
    return JobTables(engine)


@pytest.fixture
def container(
    engine: Engine,
    clock: SettableClock,
    keyring_backend: MemoryKeyring,
    job_records: JobTables,
    warm_executor: SubprocessExecutor,
) -> Iterator[Container]:
    """The server's container as `build_container` wires it, but for the clock, keyring, and
    Argon2's cost, and a pool of one worker whose reaper waits an hour, so that it never takes
    the jobs a test makes in the records, nor ends a worker by the test's clock; its workers end
    with the test, as its executor's warm runner does."""
    records = AccessTables(engine)
    cheap_hasher = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    paths = resolve_paths(os.environ)
    dispatcher = LocalDispatcher(
        job_records, paths, clock, JobTimings(reaper_period_seconds=3600), 1
    )
    jobs = Jobs(job_records, dispatcher, clock)
    store = Store(paths.data_dir)
    library = LibraryTables(engine, paths)
    try:
        yield Container(
            settings=Settings(),
            paths=paths,
            credentials=KeyringCredentialStore(keyring_backend),
            logins=Logins(records, cheap_hasher, LoginAttempts(), clock),
            api_tokens=ApiTokenIssuer(records, clock),
            preferences=PreferenceRows(engine),
            jobs=jobs,
            dispatcher=dispatcher,
            executor=warm_executor,
            catalog=MarketCatalog(store, paths.reports_dir, paths.cache_dir, jobs),
            strategies=SavedStrategies(library, warm_executor, paths.strategies_dir),
            features=SavedFeatures(library, warm_executor, paths.features_dir),
        )
    finally:
        dispatcher.close()


@pytest.fixture
def client(container: Container) -> Iterator[TestClient]:
    """A client of the app over `container`, without a built web app, at the loopback."""
    with TestClient(create_app(container, built_web_app=None), base_url=LOOPBACK) as opened:
        yield opened


@pytest.fixture
def server_log(root_log_put_back: None, tmp_path: Path) -> Path:
    """The server's log file, configured as `fefat up` configures it, and put back after."""
    return configure_server_log(tmp_path / "logs")


@pytest.fixture
def executor() -> Iterator[SubprocessExecutor]:
    """An executor over the test's own folders that starts a runner for each execution (step
    4.5)."""
    yield from _executor_leaving_nothing(warm_previews=False)


@pytest.fixture
def warm_executor() -> Iterator[SubprocessExecutor]:
    """An executor over the test's own folders that runs the previews in its warm runner (step
    4.5)."""
    yield from _executor_leaving_nothing(warm_previews=True)


def _executor_leaving_nothing(warm_previews: bool) -> Iterator[SubprocessExecutor]:
    """An executor that, once the test closes it, leaves no runner running and nothing in its
    folder, neither an execution's folder nor a runner's log."""
    paths = resolve_paths(os.environ)
    opened = SubprocessExecutor(paths, warm_previews)
    try:
        yield opened
    finally:
        opened.close()
    assert running_runners() == []
    assert sorted(paths.executions_dir.glob("*")) == []
