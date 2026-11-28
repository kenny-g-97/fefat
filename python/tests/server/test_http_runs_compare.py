"""`POST /v1/runs/compare` of step 5.10 (D-126): two saved runs of the breakout, at its default stop
and at a wider one, side by side. Done means 3: the endpoint's deltas equal the differences of the
runs' stored metrics, as each run's `run.json` holds them. The reference's figures carry no delta,
each curve is its run's daily equity over its capital, and a run is named by its id or its key;
one run, five runs, a run twice, by its key or by its id and its key, an unknown run, a run not
saved yet, and a request without the session's CSRF header are refused."""

import json
import os
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

import fefat as ff
from fefat.backtest import Run, saved_runs_in
from fefat.backtest.artifacts import RECORD_FILE
from fefat.backtest.metrics import Metrics
from fefat.config import resolve_paths
from fefat.market.engine_units import micro_units
from fefat_app.container import Container
from fefat_app.database.run_records import RunTables
from fefat_app.runs import NewRun
from local_server import STARTED_AT, logged_in
from notebook_runs import store_with
from strategy_code import ES_BREAKOUT, HYPOTHESIS
from test_http_trades import csrf
from test_run_records import REQUEST, WINDOW, the_version_id

RUN_WINDOW = ("2026-03-05", "2026-03-09")
WIDER_STOP = 3.0
"""The second run's stop in ATRs, twice the breakout's default."""


@pytest.fixture(scope="module")
def two_runs_workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A workspace holding `ES_BREAKOUT` saved as version 1 of `breakout` and two of its runs on
    the fixtures' minute bars, at its default stop and at `WIDER_STOP`, made once for the module."""
    home = tmp_path_factory.mktemp("two-runs-workspace")
    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("FEFAT_HOME", str(home / "fefat-home"))
        environment.setenv("FEFAT_DATA_DIR", str(home / "fefat-data"))
        store_with("ohlcv-1m")
        version = ff.strategy.save("breakout", ES_BREAKOUT, hypothesis=HYPOTHESIS)
        ff.backtest.run(version.strategy(), *RUN_WINDOW)
        ff.backtest.run(version.strategy(stop_atr=WIDER_STOP), *RUN_WINDOW)
        return resolve_paths(os.environ).workspace_dir


@pytest.fixture
def runs(client: TestClient, container: Container, two_runs_workspace: Path) -> tuple[Run, Run]:
    """The two saved runs, logged in and listed, so that the index holds their rows: the one at
    the default stop first, the reference."""
    logged_in(client, container)
    shutil.copytree(two_runs_workspace, resolve_paths(os.environ).workspace_dir)
    assert client.get("/v1/runs").status_code == 200
    by_stop = sorted(saved_runs_in(resolve_paths(os.environ).runs_dir), key=stop_of)
    first, second = by_stop
    return first, second


def stop_of(run: Run) -> float:
    pin = run.record.strategy.saved_version
    assert pin is not None
    stop = pin.parameters["stop_atr"]
    assert isinstance(stop, float)
    return stop


def stored_metrics(run: Run) -> Metrics:
    """The metrics `run.json` holds, read from the file itself."""
    document = json.loads((run.folder / RECORD_FILE).read_bytes())
    return Metrics.model_validate(document["metrics"])


def compared(client: TestClient, *runs: str) -> Any:
    answer = client.post("/v1/runs/compare", json={"runs": list(runs)}, headers=csrf(client))
    assert answer.status_code == 200, answer.text
    return answer.json()


def difference(figure: float | None, reference: float | None) -> float | None:
    return None if figure is None or reference is None else figure - reference


def test_the_deltas_are_the_differences_of_the_runs_stored_metrics(
    client: TestClient, runs: tuple[Run, Run]
) -> None:
    # Done means 3.
    reference, other = runs

    body = compared(client, reference.hash, other.hash)

    first, second = stored_metrics(reference), stored_metrics(other)
    deltas = body["runs"][1]["deltas"]
    assert body["runs"][0]["deltas"] is None
    assert Decimal(deltas["pnl"]) == second.pnl - first.pnl
    assert Decimal(deltas["max_drawdown"]) == (
        second.drawdown.max_drawdown - first.drawdown.max_drawdown
    )
    assert deltas["trades"] == second.trades.trades - first.trades.trades
    assert deltas["win_rate"] == difference(second.trades.win_rate, first.trades.win_rate)
    assert deltas["profit_factor"] == difference(
        second.trades.profit_factor, first.trades.profit_factor
    )
    assert deltas["expectancy_r"] == difference(
        second.trades.expectancy_r, first.trades.expectancy_r
    )
    assert deltas["sharpe"] == difference(second.daily.sharpe, first.daily.sharpe)
    assert deltas["max_drawdown_share"] == (
        second.drawdown.max_drawdown_share - first.drawdown.max_drawdown_share
    )
    assert deltas["pnl_share"] == other.pnl_share - reference.pnl_share
    assert Decimal(deltas["pnl"]) != 0


def test_each_exit_reasons_delta_is_the_difference_of_the_stored_breakdowns(
    client: TestClient, runs: tuple[Run, Run]
) -> None:
    reference, other = runs

    body = compared(client, reference.hash, other.hash)

    first = stored_metrics(reference).breakdowns.exit_reason
    second = stored_metrics(other).breakdowns.exit_reason
    assert set(body["exit_reasons"]) == {str(role) for role in (*first, *second)}
    for reason, delta in body["runs"][1]["exit_reason_deltas"].items():
        held = [breakdown.get(reason) for breakdown in (first, second)]
        trades = [0 if each is None else each.trades for each in held]
        pnl = [Decimal(0) if each is None else each.pnl for each in held]
        assert (delta["trades"], Decimal(delta["pnl"])) == (trades[1] - trades[0], pnl[1] - pnl[0])


def test_each_curve_is_its_runs_daily_equity_over_its_capital(
    client: TestClient, runs: tuple[Run, Run]
) -> None:
    body = compared(client, runs[0].hash, runs[1].hash)

    for run, answered in zip(runs, body["runs"], strict=True):
        daily = run.equity("1d")
        capital = micro_units(run.config.capital)
        assert answered["curve"]["trade_dates"] == [
            day.isoformat() for day in daily.get_column("trade_date").to_list()
        ]
        assert answered["curve"]["shares"] == [
            equity / capital for equity in daily.get_column("equity").to_list()
        ]


def test_a_run_is_named_by_its_id_or_its_key(client: TestClient, runs: tuple[Run, Run]) -> None:
    reference, other = runs
    listed = client.get("/v1/runs").json()["runs"]
    (row,) = [each for each in listed if each["run_key"] == reference.hash]

    body = compared(client, row["id"], other.hash)

    assert [each["run_key"] for each in body["runs"]] == [reference.hash, other.hash]


@pytest.mark.parametrize("count", [1, 5])
def test_fewer_than_two_runs_or_more_than_four_are_refused(
    client: TestClient, runs: tuple[Run, Run], count: int
) -> None:
    keys = [run.hash for run in runs] * 3

    answer = client.post("/v1/runs/compare", json={"runs": keys[:count]}, headers=csrf(client))

    assert answer.status_code == 422


def test_a_run_named_twice_an_unknown_run_and_one_not_saved_are_refused(
    client: TestClient, runs: tuple[Run, Run], engine: Engine
) -> None:
    reference, _ = runs
    records = RunTables(engine, resolve_paths(os.environ))
    submission = NewRun(
        strategy_version_id=the_version_id(engine),
        payload={"spec": "the backtest's"},
        parameters={"lookback": 12, "stop_atr": 1.5},
        start=WINDOW[0],
        end=WINDOW[1],
        settings=reference.config,
        request_key=REQUEST,
    )
    submitted = records.submitted(submission, 3, STARTED_AT).run

    twice = client.post(
        "/v1/runs/compare", json={"runs": [reference.hash] * 2}, headers=csrf(client)
    )
    listed = client.get("/v1/runs").json()["runs"]
    (row,) = [each for each in listed if each.get("run_key") == reference.hash]
    by_id_and_key = client.post(
        "/v1/runs/compare", json={"runs": [row["id"], reference.hash]}, headers=csrf(client)
    )
    unknown = client.post(
        "/v1/runs/compare", json={"runs": [reference.hash, "e" * 64]}, headers=csrf(client)
    )
    unsaved = client.post(
        "/v1/runs/compare", json={"runs": [reference.hash, submitted.id]}, headers=csrf(client)
    )
    unsigned = client.post("/v1/runs/compare", json={"runs": [reference.hash, submitted.id]})

    assert (twice.status_code, by_id_and_key.status_code, unknown.status_code) == (409, 409, 404)
    for refused in (twice, by_id_and_key):
        assert f"got run {reference.hash[:12]} twice" in refused.json()["detail"]
    assert unsaved.status_code == 409
    assert "Expected a saved run" in unsaved.json()["detail"]
    assert unsigned.status_code == 403
