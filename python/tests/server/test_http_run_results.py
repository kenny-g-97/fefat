"""A saved run's results over the API (step 5.7, D-116): `GET /v1/runs/{run}/stats`, `/equity`, and
`/distribution` answer what the SDK gives for the same run (Done means 1), the equity in at most
`max_points` points that keep the true maximum drawdown (Done means 3), and a run whose results
cannot be read says why, while its row still answers. From step 5.20, `/monte-carlo` answers the
SDK's too, the same for the same seed, and why for a run of one trade (its Done means 1 and 3)."""

import json
import os
import shutil
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text, update
from sqlalchemy.orm import Session

import fefat as ff
from fefat.backtest import MonteCarlo, Run, TradeDistributions
from fefat.backtest.artifacts import RECORD_FILE
from fefat.backtest.metrics import Metrics
from fefat.config import resolve_paths
from fefat.market.engine_units import micro_units, money_in_units
from fefat.market.fidelity import FidelityEra
from fefat_app.container import Container
from fefat_app.database.models import RunRow
from fefat_app.database.run_records import RunTables
from local_server import STARTED_AT, logged_in
from test_run_records import a_submission, the_run

NANOSECONDS = 1_000_000_000
KEY_OF_NO_RUN = "e" * 64
RESULTS = ["stats", "equity", "distribution", "monte-carlo"]
"""A saved run's results, each of which a run without readable results refuses alike."""


@pytest.fixture
def run(client: TestClient, container: Container, breakout_workspace: Path) -> Run:
    """The saved breakout, logged in and listed, so that the index holds its row."""
    logged_in(client, container)
    shutil.copytree(breakout_workspace, resolve_paths(os.environ).workspace_dir)
    assert client.get("/v1/runs").status_code == 200
    return the_run()


def with_record(run: Run, change: Any) -> None:
    """The run's `run.json`, changed in place by `change`, as a folder another program wrote."""
    path = run.folder / RECORD_FILE
    document = json.loads(path.read_bytes())
    change(document)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_the_statistics_are_the_sdks_for_the_same_run(client: TestClient, run: Run) -> None:
    answer = client.get(f"/v1/runs/{run.hash}/stats")

    assert answer.status_code == 200
    body = answer.json()
    assert Metrics.model_validate(body["metrics"]) == run.metrics
    assert body["pnl_share"] == run.pnl_share
    assert body["currency"] == run.record.instrument.currency
    eras = tuple(FidelityEra.model_validate(era) for era in body["fidelity_eras"])
    assert eras == run.record.fidelity_eras
    assert tuple(body["warnings"]) == run.record.warnings


def test_a_run_is_read_by_its_rows_id_too(client: TestClient, run: Run) -> None:
    row = client.get(f"/v1/runs/{run.hash}").json()

    by_id = client.get(f"/v1/runs/{row['id']}/stats")

    assert by_id.json() == client.get(f"/v1/runs/{run.hash}/stats").json()


def test_the_equity_is_the_sdks_in_the_currency_and_whole_seconds(
    client: TestClient, run: Run
) -> None:
    body = client.get(f"/v1/runs/{run.hash}/equity").json()

    curve = ff.backtest.equity_curve(run)
    assert body["capital"] == float(run.config.capital)
    assert body["time"] == (curve.get_column("ts") // NANOSECONDS).to_list()
    assert tuple(body["equity"]) == money_in_units(curve.get_column("equity"))
    assert tuple(body["drawdown"]) == money_in_units(curve.get_column("drawdown"))


def test_the_equity_keeps_the_true_maximum_drawdown_in_the_points_asked_for(
    client: TestClient, run: Run
) -> None:
    # Done means 3, on the run's own figure and on a curve that recovers: its deepest fall lies
    # mid-bucket of a rising account, its trough neither the bucket's lowest nor its highest,
    # where the seeded curve's deepest point is its last decision, which is always kept.
    body = client.get(f"/v1/runs/{run.hash}/equity", params={"max_points": 90}).json()
    assert len(body["time"]) <= 90
    assert len(body["time"]) == len(body["equity"]) == len(body["drawdown"])
    assert max(body["drawdown"]) == float(run.metrics.drawdown.max_drawdown)

    decisions = run.equity("5m")
    assert decisions.height > 500
    capital = micro_units(run.config.capital)
    rising = [capital + at * 1_000_000 for at in range(decisions.height)]
    buckets = (90 - 2) // 3
    trough = (15 * decisions.height // buckets + 16 * decisions.height // buckets) // 2
    rising[trough] -= 5_000_000
    written = decisions.with_columns(equity=pl.Series(rising, dtype=pl.Int64))
    written.write_parquet(run.folder / "equity.parquet")
    account = pl.Series("equity", [capital, *rising], dtype=pl.Int64)
    deepest = ff.backtest.running_drawdown(account).max()
    assert deepest == 4_000_000

    recovered = client.get(f"/v1/runs/{run.hash}/equity", params={"max_points": 90}).json()

    assert len(recovered["time"]) <= 90
    assert max(recovered["drawdown"]) == 4.0


@pytest.mark.parametrize("max_points", [4, 10_001])
def test_points_out_of_bounds_are_refused(client: TestClient, run: Run, max_points: int) -> None:
    answer = client.get(f"/v1/runs/{run.hash}/equity", params={"max_points": max_points})

    assert answer.status_code == 422


def test_the_distributions_are_the_sdks(client: TestClient, run: Run) -> None:
    body = client.get(f"/v1/runs/{run.hash}/distribution").json()

    assert TradeDistributions.model_validate(body) == ff.backtest.trade_distributions(run.trades)
    assert sum(body["pnl"]["trades"]) == run.metrics.trades.trades


def test_the_monte_carlo_is_the_sdks_for_the_same_run_seed_and_paths(
    client: TestClient, run: Run
) -> None:
    # Done means 1 of step 5.20: API equals SDK.
    asked = client.get(f"/v1/runs/{run.hash}/monte-carlo", params={"paths": 300, "seed": 3})
    left_out = client.get(f"/v1/runs/{run.hash}/monte-carlo")

    assert asked.status_code == 200
    assert MonteCarlo.model_validate(asked.json()) == ff.backtest.monte_carlo(run, 300, 3)
    assert MonteCarlo.model_validate(left_out.json()) == ff.backtest.monte_carlo(run)


def test_the_same_seed_answers_the_same_monte_carlo_and_another_seed_another(
    client: TestClient, run: Run
) -> None:
    # Done means 3 of step 5.20.
    address = f"/v1/runs/{run.hash}/monte-carlo"

    first = client.get(address, params={"seed": 4}).json()

    assert client.get(address, params={"seed": 4}).json() == first
    assert client.get(address, params={"seed": 5}).json() != first


def test_a_run_of_one_trade_answers_why_it_has_no_monte_carlo(client: TestClient, run: Run) -> None:
    # Done means 3 of step 5.20.
    trades = run.folder / "trades.parquet"
    pl.read_parquet(trades).head(1).write_parquet(trades)

    answer = client.get(f"/v1/runs/{run.hash}/monte-carlo")

    assert answer.status_code == 200
    assert answer.json() == {
        "kind": "too_few_trades",
        "trades": 1,
        "reason": "This run made 1 trade, and a Monte Carlo draws from at least 2.",
    }


def test_the_most_paths_and_points_a_monte_carlo_allows_are_drawn(
    client: TestClient, run: Run
) -> None:
    answer = client.get(
        f"/v1/runs/{run.hash}/monte-carlo", params={"paths": 10_000, "max_points": 10_000}
    )

    assert answer.status_code == 200
    assert answer.json()["paths"] == 10_000


@pytest.mark.parametrize(
    "asked",
    [
        {"paths": 99},
        {"paths": 10_001},
        {"seed": -1},
        {"max_points": 4},
        {"max_points": 10_001},
    ],
)
def test_a_monte_carlo_asked_out_of_bounds_is_refused(
    client: TestClient, run: Run, asked: dict[str, int]
) -> None:
    answer = client.get(f"/v1/runs/{run.hash}/monte-carlo", params=asked)

    assert answer.status_code == 422


@pytest.mark.parametrize("result", RESULTS)
def test_an_unknown_run_answers_404(client: TestClient, run: Run, result: str) -> None:
    assert run.hash != KEY_OF_NO_RUN

    answer = client.get(f"/v1/runs/{KEY_OF_NO_RUN}/{result}")

    assert answer.status_code == 404
    assert "names none" in answer.json()["detail"]


@pytest.mark.parametrize("result", RESULTS)
def test_a_run_not_saved_yet_is_refused(
    client: TestClient, run: Run, engine: Engine, result: str
) -> None:
    records = RunTables(engine, resolve_paths(os.environ))
    assert run.hash
    submitted = records.submitted(a_submission(engine), 3, STARTED_AT).run

    answer = client.get(f"/v1/runs/{submitted.id}/{result}")

    assert answer.status_code == 409
    assert "Expected a saved run" in answer.json()["detail"]
    assert "queued" in answer.json()["detail"]


def test_a_run_whose_job_ended_is_told_to_run_it_again(
    client: TestClient, container: Container, run: Run, engine: Engine
) -> None:
    # The reviews: a job that ended never saves, so its run has nothing to wait for.
    records = RunTables(engine, resolve_paths(os.environ))
    assert run.hash
    submitted = records.submitted(a_submission(engine), 3, STARTED_AT).run
    container.runs.cancel(submitted.id)

    detail = client.get(f"/v1/runs/{submitted.id}/stats").json()["detail"]

    assert "cancelled" in detail
    assert "run the backtest again" in detail
    assert "come once" not in detail


@pytest.mark.parametrize("result", RESULTS)
def test_a_folder_that_is_gone_says_so(client: TestClient, run: Run, result: str) -> None:
    shutil.rmtree(run.folder)

    answer = client.get(f"/v1/runs/{run.hash}/{result}")

    assert answer.status_code == 409
    assert "is gone" in answer.json()["detail"]
    assert "Run the backtest again" in answer.json()["detail"]


@pytest.mark.parametrize("result", RESULTS)
def test_a_run_another_engine_saved_is_refused_in_the_engines_words(
    client: TestClient, run: Run, result: str
) -> None:
    written_by = run.record.versions.engine - 1
    with_record(run, lambda document: document["versions"].update(engine=written_by))

    answer = client.get(f"/v1/runs/{run.hash}/{result}")

    assert answer.status_code == 409
    assert f"got one of version {written_by}" in answer.json()["detail"]
    assert "run it again with this engine" in answer.json()["detail"]
    assert str(run.folder) not in answer.json()["detail"]
    assert f"run {run.hash[:12]}" in answer.json()["detail"]


def test_a_folder_copied_by_hand_is_refused_in_the_sdks_words(client: TestClient, run: Run) -> None:
    with_record(run, lambda document: document.update(run_key=KEY_OF_NO_RUN))

    answer = client.get(f"/v1/runs/{run.hash}/stats")

    assert answer.status_code == 409
    assert "copied or renamed by hand" in answer.json()["detail"]
    assert str(run.folder) not in answer.json()["detail"]


def test_a_folder_part_gone_says_to_delete_it_first(client: TestClient, run: Run) -> None:
    # A new run of the same inputs opens a folder it finds saved, so it must go first.
    (run.folder / "trades.parquet").unlink()

    answer = client.get(f"/v1/runs/{run.hash}/distribution")

    assert answer.status_code == 409
    assert "incomplete or damaged" in answer.json()["detail"]
    assert f"Delete workspaces/default/artifacts/runs/{run.hash}" in answer.json()["detail"]
    assert str(run.folder) not in answer.json()["detail"]


@pytest.mark.parametrize(
    ("result", "artifact"),
    [("equity", "equity"), ("distribution", "trades"), ("monte-carlo", "trades")],
)
def test_a_damaged_artifact_says_to_delete_the_folder(
    client: TestClient, run: Run, result: str, artifact: str
) -> None:
    path = run.folder / f"{artifact}.parquet"
    path.write_bytes(path.read_bytes()[:64])

    answer = client.get(f"/v1/runs/{run.hash}/{result}")

    assert answer.status_code == 409
    assert "incomplete or damaged" in answer.json()["detail"]
    assert str(run.folder) not in answer.json()["detail"]


def test_a_row_whose_metrics_another_engine_shaped_keeps_its_page(
    client: TestClient, run: Run, engine: Engine
) -> None:
    # Your answer at the plan: such a run stays listed, and its page says which engine saved it.
    key_figures = {
        "pnl": str(run.metrics.pnl),
        "trades": {"trades": run.metrics.trades.trades},
        "drawdown": {"max_drawdown": str(run.metrics.drawdown.max_drawdown)},
        "robustness": {"verdict": str(run.metrics.robustness.verdict)},
    }
    with Session(engine) as session, session.begin():
        session.execute(text("DROP TRIGGER runs_no_update"))
        session.execute(
            update(RunRow).where(RunRow.run_key == run.hash).values(metrics_json=key_figures)
        )
    written_by = run.record.versions.engine - 1
    with_record(run, lambda document: document["versions"].update(engine=written_by))

    detail = client.get(f"/v1/runs/{run.hash}")
    results = client.get(f"/v1/runs/{run.hash}/stats")

    assert detail.status_code == 200
    assert detail.json()["key_metrics"]["trades"] == run.metrics.trades.trades
    assert "metrics" not in detail.json()
    assert results.status_code == 409


@pytest.mark.parametrize("result", RESULTS)
def test_the_results_need_a_login(client: TestClient, result: str) -> None:
    assert client.get(f"/v1/runs/{KEY_OF_NO_RUN}/{result}").status_code == 401
