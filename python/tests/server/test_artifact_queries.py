"""DuckDB over a saved run's artifacts (step 5.8, `fefat_app.artifact_queries`): the trader's one
SELECT reads the run's views in the instrument's units and is refused past its bytes and its time,
and a value DuckDB answers reaches the JSON as a browser reads it unchanged."""

import os
import re
import shutil
from pathlib import Path

import pytest

from fefat.backtest import Run
from fefat.config import resolve_paths
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
