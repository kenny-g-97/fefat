"""The app's database of step 4.1 (`01-architecture.md` section 5, D-83, D-85): `fefat.sqlite` in
WAL mode with foreign keys on; its schema made and emptied by the migrations that ship in the
package (Done means 1), alike with the models, with the login sessions and API tokens of step
4.2 (D-86) and the strategies' tables of step 5.2 (D-93); and the rows that index a file
insert-only, an update or a delete of one refused (Done means 2, ADR-0020)."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine, inspect, select
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from fefat.market.importers.profiles import ProfileKind
from fefat.strategy import StrategyKind
from fefat_app.database.models import (
    ApiTokenRow,
    Base,
    FeatureRow,
    FeatureValidationRow,
    FeatureVersionRow,
    ImportProfileRow,
    LoginSessionRow,
    StrategyRow,
    StrategyVersionFeatureRow,
    StrategyVersionRow,
    WorkspaceRow,
)
from fefat_app.database.schema import empty_schema, opened_database, upgrade_schema
from fefat_app.database.uuid7 import new_uuid7

TABLES = {
    "settings",
    "workspaces",
    "features",
    "feature_versions",
    "feature_validations",
    "import_profiles",
    "jobs",
    "events",
    "sessions",
    "api_tokens",
    "strategies",
    "strategy_versions",
    "strategy_version_features",
}
INDEX_TABLES = [
    "feature_versions",
    "feature_validations",
    "import_profiles",
    "strategy_versions",
    "strategy_version_features",
]
LATEST_REVISION = "0004"
SAVED_AT = datetime(2026, 11, 6, 12, 30, tzinfo=UTC)


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """The database of a home not made yet."""
    with opened_database(tmp_path / "home" / "fefat.sqlite") as opened:
        yield opened


def table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def index_one_of_each(engine: Engine) -> None:
    """A row of each table that indexes a file, with the rows they refer to."""
    workspace_id, feature_id, version_id = new_uuid7(), new_uuid7(), new_uuid7()
    strategy_id, strategy_version_id = new_uuid7(), new_uuid7()
    with Session(engine) as session, session.begin():
        session.add(WorkspaceRow(id=workspace_id, name="default", path="workspaces/default"))
        session.flush()
        session.add(FeatureRow(id=feature_id, workspace_id=workspace_id, name="gap"))
        session.flush()
        session.add(
            FeatureVersionRow(
                id=version_id,
                feature_id=feature_id,
                version_no=1,
                content_hash="a" * 64,
                code="@ff.feature()\ndef gap(bars): ...\n",
                params_schema_json={"properties": {}, "type": "object"},
                inputs_json=[],
                outputs_json={"gap": "other"},
                warmup="lambda n: n",
                warmup_sessions=0,
                combination_json=None,
                created_at=SAVED_AT,
            )
        )
        session.flush()
        session.add(
            FeatureValidationRow(
                feature_version_id=version_id,
                report_sha256="b" * 64,
                feature_name="gap",
                feature_hash="a" * 64,
                instrument="ES",
                timeframe="1m",
                provider="synthetic",
                window_start=date(2026, 2, 11),
                window_end=date(2026, 2, 19),
                parameters_json={},
                passed=True,
                created_at=SAVED_AT,
            )
        )
        session.add(ImportProfileRow(kind=ProfileKind.MARKET_DATA, name="mine", sha256="c" * 64))
        session.add(
            StrategyRow(
                id=strategy_id, workspace_id=workspace_id, name="breakout", kind=StrategyKind.SIGNAL
            )
        )
        session.flush()
        session.add(
            StrategyVersionRow(
                id=strategy_version_id,
                strategy_id=strategy_id,
                version_no=1,
                content_hash="f" * 64,
                code="def strategy() -> ff.SignalStrategy: ...\n",
                hypothesis="A close above the highest of the hour runs on.",
                instrument="MES",
                timeframe="5m",
                params_schema_json={"properties": {}, "type": "object"},
                changelog="",
                created_at=SAVED_AT,
            )
        )
        session.flush()
        session.add(
            StrategyVersionFeatureRow(
                strategy_version_id=strategy_version_id,
                feature_version_id=version_id,
                created_at=SAVED_AT,
            )
        )


def log_in_once(engine: Engine) -> None:
    """A login session and an API token, the app's own state of step 4.2."""
    with Session(engine) as session, session.begin():
        session.add(
            LoginSessionRow(
                token_hash="d" * 64,
                created_at=SAVED_AT,
                expires_at=SAVED_AT,
                last_seen_at=SAVED_AT,
            )
        )
        session.add(ApiTokenRow(name="notebook", token_hash="e" * 64, created_at=SAVED_AT))


def test_upgrade_makes_the_schema_in_a_new_file(engine: Engine) -> None:
    # Done means 1.
    revision = upgrade_schema(engine)

    assert revision == LATEST_REVISION
    assert table_names(engine) == TABLES | {"alembic_version"}


def test_the_database_runs_in_wal_mode_with_foreign_keys_on(engine: Engine) -> None:
    with engine.connect() as connection:
        journal = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_keys").scalar()

    assert (journal, foreign_keys) == ("wal", 1)


def test_downgrade_to_base_empties_it_and_upgrade_makes_it_again(engine: Engine) -> None:
    # Done means 1: `alembic downgrade base` leaves only Alembic's own table, without a row.
    upgrade_schema(engine)
    index_one_of_each(engine)
    log_in_once(engine)

    empty_schema(engine)

    emptied = table_names(engine)
    with engine.connect() as connection:
        revisions = connection.exec_driver_sql("SELECT count(*) FROM alembic_version").scalar()
    assert (emptied, revisions) == ({"alembic_version"}, 0)
    assert upgrade_schema(engine) == LATEST_REVISION
    assert table_names(engine) == TABLES | {"alembic_version"}


def test_the_migrations_make_the_tables_the_models_describe(engine: Engine) -> None:
    upgrade_schema(engine)

    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        differences = compare_metadata(context, Base.metadata)

    assert differences == []


def test_schema_changes_run_in_one_transaction_with_the_rest(engine: Engine) -> None:
    # A migration that fails leaves the database as it was (`fefat_app.database.schema`).
    with pytest.raises(RuntimeError, match="a migration failed"), engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE half_made (id INTEGER)")
        raise RuntimeError("a migration failed")

    assert "half_made" not in table_names(engine)


def test_a_transaction_takes_the_write_lock_when_it_begins(engine: Engine, tmp_path: Path) -> None:
    # A second writer waits at its own BEGIN, where a transaction that read first would fail
    # halfway in WAL mode (`fefat_app.database.schema`).
    upgrade_schema(engine)
    other = sqlite3.connect(tmp_path / "home" / "fefat.sqlite", timeout=0)

    try:
        with (
            engine.begin(),
            pytest.raises(sqlite3.OperationalError, match="database is locked"),
        ):
            other.execute("BEGIN IMMEDIATE")
    finally:
        other.close()


@pytest.mark.parametrize("table", INDEX_TABLES)
def test_a_row_that_indexes_a_file_is_never_updated_or_deleted(engine: Engine, table: str) -> None:
    # Done means 2 for feature_versions, and the other two tables that index a file alike.
    upgrade_schema(engine)
    index_one_of_each(engine)

    with (
        pytest.raises(IntegrityError, match=f"{table} rows are never updated"),
        engine.begin() as connection,
    ):
        connection.exec_driver_sql(f"UPDATE {table} SET created_at = created_at")
    with (
        pytest.raises(IntegrityError, match=f"{table} rows are never deleted"),
        engine.begin() as connection,
    ):
        connection.exec_driver_sql(f"DELETE FROM {table}")

    with engine.connect() as connection:
        assert connection.exec_driver_sql(f"SELECT count(*) FROM {table}").scalar() == 1


def test_a_feature_version_changed_through_the_models_is_refused(engine: Engine) -> None:
    # Done means 2, as the app's code would try it.
    upgrade_schema(engine)
    index_one_of_each(engine)

    with (
        pytest.raises(IntegrityError, match="feature_versions rows are never updated"),
        Session(engine) as session,
        session.begin(),
    ):
        version = session.scalars(select(FeatureVersionRow)).one()
        version.code = "changed"

    with Session(engine) as session:
        assert session.scalars(select(FeatureVersionRow.code)).one().startswith("@ff.feature")


def test_an_instant_is_kept_in_utc_and_a_naive_one_is_refused(engine: Engine) -> None:
    upgrade_schema(engine)
    index_one_of_each(engine)

    with Session(engine) as session:
        saved_at = session.scalars(select(FeatureVersionRow.created_at)).one()
    with (
        pytest.raises(StatementError, match="Expected an aware instant, got the naive"),
        Session(engine) as session,
    ):
        session.add(WorkspaceRow(name="other", path="x", created_at=datetime(2026, 11, 6)))
        session.flush()

    assert saved_at == SAVED_AT
    assert saved_at.tzinfo is not None
