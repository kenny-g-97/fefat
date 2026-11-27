"""DuckDB over a saved run's artifacts (step 5.8, `fefat_app.artifact_queries`): the trader's one
SELECT reads the run's views in the instrument's units, each column `UNIT_COLUMNS` names exactly,
and is refused past its rows, its bytes, which DuckDB measures before Python reads a row, whatever
the answer's columns are named, and its time, and where its read answers more than its measure;
a value DuckDB answers reaches the JSON as a browser reads it unchanged, and no text loses a
character to a home folder at the root."""

import os
import re
import shutil
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from fefat.backtest import Run
from fefat.backtest.schemas import ARTIFACT_SCHEMAS, UNIT_COLUMNS, Unit
from fefat.config import resolve_paths
from fefat.market.engine_units import MONEY_DECIMALS, PRICE_DECIMALS, PRICE_SCALE
from fefat_app import artifact_queries
from fefat_app.artifact_queries import DuckDbQueries
from fefat_app.trades import QueryRefusedError
from test_run_records import the_run


@pytest.fixture
def run(breakout_workspace: Path) -> Run:
    """The saved breakout, copied into the test's home."""
    shutil.copytree(breakout_workspace, resolve_paths(os.environ).workspace_dir)
    return the_run()


def test_an_answer_past_its_bytes_is_refused(run: Run) -> None:
    with pytest.raises(QueryRefusedError, match="1,000 bytes"):
        DuckDbQueries(most_bytes=1_000).select(run.folder, "SELECT * FROM fills")


@pytest.mark.parametrize(
    "sql", ["SELECT list(f) FROM fills f", "SELECT 0 AS answer, list(f) AS fills FROM fills f"]
)
def test_an_answer_past_its_bytes_is_refused_before_python_reads_a_row(
    run: Run, monkeypatch: pytest.MonkeyPatch, sql: str
) -> None:
    def unread(*read: object) -> object:
        raise AssertionError(f"Expected the answer refused in DuckDB, got {read[0]!r} read")

    with monkeypatch.context() as patched:
        patched.setattr(artifact_queries, "json_value", unread)

        with pytest.raises(QueryRefusedError, match="1,000 bytes"):
            DuckDbQueries(most_bytes=1_000).select(run.folder, sql)


def test_a_read_that_answers_more_rows_than_its_measure_is_refused(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    # As a sample can: the measure here says one row of no bytes, the read answers four.
    with monkeypatch.context() as patched:
        patched.setattr(artifact_queries, "_MEASURED", "SELECT 1, 0")

        with pytest.raises(QueryRefusedError, match="more than 3 rows"):
            DuckDbQueries(most_rows=3).select(run.folder, "SELECT * FROM range(4)")


def test_a_home_folder_at_the_root_changes_no_text(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(run.folder.anchor)
    text = f"{root.as_posix()}data/ES/2026-03"

    with monkeypatch.context() as patched:
        patched.setattr(Path, "home", lambda: root)
        answer = DuckDbQueries().select(run.folder, f"SELECT '{text}' AS text")

    assert answer.rows == ((text,),)


def test_each_unit_column_reads_in_the_instruments_units(run: Run) -> None:
    queries = DuckDbQueries(most_rows=1_000_000, most_bytes=1_000_000_000)

    for artifact, units in UNIT_COLUMNS.items():
        raw = pl.read_parquet(run.folder / f"{artifact}.parquet")
        for column, unit in units.items():
            if column not in raw.columns:
                assert column not in ARTIFACT_SCHEMAS[artifact], (artifact, column)
                continue
            read = "epoch_ns" if unit is Unit.INSTANT else ""
            answer = queries.select(run.folder, f'SELECT {read}("{column}") FROM {artifact}')
            expected = [
                None if engine is None else _in_units(engine, unit, raw.schema[column])
                for engine in raw.get_column(column).to_list()
            ]
            assert [_figure(row[0]) for row in answer.rows] == expected, (artifact, column)


def _in_units(engine: int | float, unit: Unit, kind: pl.DataType) -> object:
    """What the view of a column in engine units answers for `engine`: an instant's nanoseconds
    (as `epoch_ns` reads them back), a float's price, or the decimal a whole number scales to."""
    if unit is Unit.INSTANT:
        return engine
    if kind == pl.Float64:
        return engine / PRICE_SCALE
    places = MONEY_DECIMALS if unit is Unit.MONEY else PRICE_DECIMALS
    return Decimal(int(engine)).scaleb(-places)


def _figure(value: object) -> object:
    """An answer's value as the figure it writes: a text of a whole number or a decimal as
    that number, whatever zeros end it."""
    if isinstance(value, str):
        return int(value) if value.lstrip("-").isdigit() else Decimal(value)
    return value


def test_a_query_past_its_time_is_stopped(run: Run) -> None:
    quick = DuckDbQueries(timeout_seconds=0.2)

    with pytest.raises(QueryRefusedError, match=re.escape("0.2 seconds")):
        quick.select(
            run.folder, "SELECT sum(a.range * b.range) FROM range(100000) a, range(100000) b"
        )


def test_an_answer_past_its_rows_is_refused(run: Run) -> None:
    with pytest.raises(QueryRefusedError, match="more than 3 rows"):
        DuckDbQueries(most_rows=3).select(run.folder, "SELECT * FROM range(4)")


def test_values_a_browser_would_change_are_sent_as_text(run: Run) -> None:
    answer = DuckDbQueries().select(
        run.folder,
        "SELECT 9007199254740993::BIGINT AS big, 12::BIGINT AS small, 'nan'::DOUBLE AS nan, "
        "1.5::DOUBLE AS half, 2.50::DECIMAL(4, 2) AS money, DATE '2026-03-05' AS day, "
        "TIMESTAMP '2026-03-05 14:35:00.5' AS instant, [1, 2] AS listed, {'a': 1} AS keyed, "
        "NULL AS nothing",
    )

    ((big, small, nan, half, money, day, instant, listed, keyed, nothing),) = answer.rows
    assert (big, small, nan, half, money) == ("9007199254740993", 12, "nan", 1.5, "2.50")
    assert (day, instant, listed, keyed, nothing) == (
        "2026-03-05",
        "2026-03-05T14:35:00.500000Z",
        [1, 2],
        {"a": 1},
        None,
    )


def test_the_views_name_every_artifact_and_the_trades_their_row(run: Run) -> None:
    answer = DuckDbQueries().select(run.folder, "SHOW TABLES")
    trades = DuckDbQueries().select(run.folder, "SELECT trade FROM trades ORDER BY trade LIMIT 3")

    assert sorted(str(row[0]) for row in answer.rows) == sorted(
        [
            "costs",
            "equity",
            "equity_daily",
            "fills",
            "log",
            "orders",
            "signals",
            "trade_paths",
            "trades",
        ]
    )
    assert trades.rows == ((0,), (1,), (2,))
