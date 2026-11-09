"""The adapters behind the app's ports, built once (`08-code-design.md` section 1, D-27):
`build_container` chooses each port's adapter and the services over them, which the server's
routes and the commands reach, so that nothing builds an adapter inside itself."""

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial

import keyring
from argon2 import PasswordHasher
from sqlalchemy import Engine

from fefat.config import FefatPaths, Settings, load_settings
from fefat_app.credentials import KeyringCredentialStore
from fefat_app.database.access_records import AccessTables
from fefat_app.database.job_records import JobTables
from fefat_app.database.preferences import PreferenceRows
from fefat_app.database.schema import opened_database, upgrade_schema
from fefat_app.executor.subprocess_executor import SubprocessExecutor
from fefat_app.jobs.dispatcher import LocalDispatcher
from fefat_app.jobs.worker import JobTimings
from fefat_app.ports import CredentialStore, Dispatcher, Executor, Preferences
from fefat_app.services.api_tokens import ApiTokenIssuer
from fefat_app.services.jobs import Jobs
from fefat_app.services.logins import LoginAttempts, Logins


@dataclass(frozen=True)
class Container:
    """What the server's routes reach: the settings of `config.toml`, the folders of
    `FEFAT_HOME` and the data, the credential store, the logins, the API tokens, the trader's
    preferences, the jobs, and their dispatcher, which the server starts and closes, and the
    executor of the trader's code, whose warm runner `opened_container` ends."""

    settings: Settings
    paths: FefatPaths
    credentials: CredentialStore
    logins: Logins
    api_tokens: ApiTokenIssuer
    preferences: Preferences
    jobs: Jobs
    dispatcher: Dispatcher
    executor: Executor


def credential_store() -> CredentialStore:
    """The credential store over the keyring backend that keyring finds, the Windows credential
    store here (`fefat_app.credentials`); `fefat secrets` needs it alone, without the database."""
    return KeyringCredentialStore(keyring.get_keyring())


def build_container(engine: Engine, settings: Settings, paths: FefatPaths) -> Container:
    """The adapters of this machine over the database of `engine`: the access records, the
    preferences, and the jobs in its tables, Argon2 at argon2-cffi's default cost, the system's
    clock in UTC, the jobs' process pool of `config.toml`'s size, and the executor with its warm
    runner for the previews, one for the workspace, neither starting a process before its first
    job or execution."""
    records = AccessTables(engine)
    clock = partial(datetime.now, UTC)
    job_records = JobTables(engine)
    dispatcher = LocalDispatcher(
        job_records, paths, clock, JobTimings(), settings.process_pool_size
    )
    return Container(
        settings=settings,
        paths=paths,
        credentials=credential_store(),
        logins=Logins(records, PasswordHasher(), LoginAttempts(), clock),
        api_tokens=ApiTokenIssuer(records, clock),
        preferences=PreferenceRows(engine),
        jobs=Jobs(job_records, dispatcher, clock),
        dispatcher=dispatcher,
        executor=SubprocessExecutor(paths, warm_previews=True),
    )


@contextmanager
def opened_container(paths: FefatPaths) -> Generator[Container]:
    """The container over the database of `paths`, migrated to the latest schema, with the
    settings of its `config.toml`, read first, so that settings it refuses stop everything
    before the database is made; on leaving, the executor's warm runner ends and the database
    closes."""
    settings = load_settings(paths.config_file)
    with opened_database(paths.database_file) as engine:
        upgrade_schema(engine)
        container = build_container(engine, settings, paths)
        try:
            yield container
        finally:
            container.executor.close()
