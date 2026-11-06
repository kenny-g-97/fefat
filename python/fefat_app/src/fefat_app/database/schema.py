"""The app's database file and its schema (`01-architecture.md` section 5, D-83): `opened_database`
opens `fefat.sqlite` in WAL mode with foreign keys on, and `upgrade_schema` and `empty_schema`
run the migrations under `migrations/`, which ship inside the package, up to the head and down to
the base, with no `alembic.ini`.

Each transaction is SQLite's own, begun here rather than by Python's `sqlite3`, which leaves a
schema change outside it: so a migration's changes and its revision are kept whole or not at
all, and a batch migration that rebuilds a table never loses its rows halfway. It begins with
`BEGIN IMMEDIATE`, taking the write lock at once, so that a second writer, such as a command
run while the server writes, waits for the first rather than failing halfway, as a transaction
that reads before it writes does in WAL mode; it waits up to `BUSY_TIMEOUT_MS`. A transaction
that only reads, through `reading`, begins deferred instead, so that it neither waits for a
writer nor holds one up, WAL mode giving it a snapshot; and a write that may be given up, such
as a session's last-seen time, through `not_waiting`, is refused at once with SQLite's busy
error while another writer holds the database (step 4.2: the server reads at every request).

Foreign keys are on for every connection, and SQLite ignores turning them off inside a
transaction, so a later migration that rebuilds a table another references in batch mode
defers them instead (`PRAGMA defer_foreign_keys=ON`); and since a rebuilt table loses its
triggers, a migration that rebuilds one of the tables that index a file makes its triggers
again (the first migration, `v0001_app_state`)."""

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
READ_ONLY = "fefat_read_only"
"""The execution option of `reading`'s engine."""
NOT_WAITING = "fefat_not_waiting"
"""The execution option of `not_waiting`'s engine."""
BUSY_TIMEOUT_MS = 5000
"""How long a transaction waits for another writer, Python's `sqlite3`'s own five seconds."""


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


def reading(engine: Engine) -> Engine:
    """`engine` for transactions that only read, which begin deferred (module docstring)."""
    return engine.execution_options(**{READ_ONLY: True})


def not_waiting(engine: Engine) -> Engine:
    """`engine` for writes that may be given up, refused at once while another writer holds the
    database (module docstring)."""
    return engine.execution_options(**{NOT_WAITING: True})


def _on_begin(connection: Connection) -> None:
    options = connection.get_execution_options()
    waits = 0 if options.get(NOT_WAITING) else BUSY_TIMEOUT_MS
    connection.exec_driver_sql(f"PRAGMA busy_timeout = {waits}")
    if options.get(READ_ONLY):
        connection.exec_driver_sql("BEGIN")
        return
    connection.exec_driver_sql("BEGIN IMMEDIATE")
