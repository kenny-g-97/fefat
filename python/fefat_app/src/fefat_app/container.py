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
from fefat_app.database.schema import opened_database, upgrade_schema
from fefat_app.ports import CredentialStore
from fefat_app.services.api_tokens import ApiTokenIssuer
from fefat_app.services.logins import LoginAttempts, Logins


@dataclass(frozen=True)
class Container:
    """What the server's routes reach: the settings of `config.toml`, the credential store, the
    logins, and the API tokens."""

    settings: Settings
    credentials: CredentialStore
    logins: Logins
    api_tokens: ApiTokenIssuer


def credential_store() -> CredentialStore:
    """The credential store over the keyring backend that keyring finds, the Windows credential
    store here (`fefat_app.credentials`); `fefat secrets` needs it alone, without the database."""
    return KeyringCredentialStore(keyring.get_keyring())


def build_container(engine: Engine, settings: Settings) -> Container:
    """The adapters of this machine over the database of `engine`: the access records in its
    tables, Argon2 at argon2-cffi's default cost, and the system's clock in UTC."""
    records = AccessTables(engine)
    clock = partial(datetime.now, UTC)
    return Container(
        settings=settings,
        credentials=credential_store(),
        logins=Logins(records, PasswordHasher(), LoginAttempts(), clock),
        api_tokens=ApiTokenIssuer(records, clock),
    )


@contextmanager
def opened_container(paths: FefatPaths) -> Generator[Container]:
    """The container over the database of `paths`, migrated to the latest schema, with the
    settings of its `config.toml`, read first, so that settings it refuses stop everything
    before the database is made; the database closes on leaving."""
    settings = load_settings(paths.config_file)
    with opened_database(paths.database_file) as engine:
        upgrade_schema(engine)
        yield build_container(engine, settings)
