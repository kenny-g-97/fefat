"""The app's database file and its schema (`01-architecture.md` section 5, D-83): `opened_database`
opens `fefat.sqlite` in WAL mode with foreign keys on, and `upgrade_schema` and `empty_schema`
run the migrations under `migrations/`, which ship inside the package, up to the head and down to
the base, with no `alembic.ini`.

Each transaction is SQLite's own, begun here rather than by Python's `sqlite3`, which leaves a
schema change outside it: so a migration's changes and its revision are kept whole or not at
all, and a batch migration that rebuilds a table never loses its rows halfway. Foreign keys are
on for every connection, so a later migration that rebuilds a table that another references
turns them off for its run."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import URL, Connection, Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.pool import ConnectionPoolEntry

MIGRATIONS = Path(__file__).with_name("migrations")


@contextmanager
def opened_database(database_file: Path) -> Generator[Engine]:
    """The engine of the database `database_file`, made with its folder where there is none,
    and closed when the block ends, so that no connection keeps the file open."""
    database_file.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(URL.create("sqlite+pysqlite", database=str(database_file)))
    event.listen(engine, "connect", _on_connect)
    event.listen(engine, "begin", _on_begin)
    try:
        yield engine
    finally:
        engine.dispose()


def upgrade_schema(engine: Engine) -> str:
    """Migrate the database up to the head, in one transaction; the revision it is at."""
    with engine.begin() as connection:
        command.upgrade(_configuration(connection), "head")
        return _revision(connection)


def empty_schema(engine: Engine) -> None:
    """Migrate the database down to the base, before the first migration, in one transaction:
    every table is dropped but Alembic's own, which keeps no revision."""
    with engine.begin() as connection:
        command.downgrade(_configuration(connection), "base")


def _configuration(connection: Connection) -> Config:
    configuration = Config()
    configuration.set_main_option("script_location", str(MIGRATIONS).replace("%", "%%"))
    configuration.attributes["connection"] = connection
    return configuration


def _revision(connection: Connection) -> str:
    revision = MigrationContext.configure(connection).get_current_revision()
    if revision is None:
        raise ValueError("Expected the database at a revision after its upgrade, got none.")
    return revision


def _on_connect(connection: DBAPIConnection, record: ConnectionPoolEntry) -> None:
    """WAL mode and foreign keys on each new connection, and transactions left to `_on_begin`."""
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
    connection.isolation_level = None


def _on_begin(connection: Connection) -> None:
    connection.exec_driver_sql("BEGIN")
