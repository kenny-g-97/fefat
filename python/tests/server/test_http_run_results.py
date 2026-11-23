"""A saved run's results over the API (step 5.7, D-116): `GET /v1/runs/{run}/stats`, `/equity`, and
`/distribution` answer what the SDK gives for the same run (Done means 1), the equity in at most
`max_points` points that keep the true maximum drawdown (Done means 3), and a run whose results
cannot be read says why, while its row still answers."""

import json
import os
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text, update
from sqlalchemy.orm import Session

import fefat as ff
from fefat.backtest import Run, TradeDistributions
from fefat.backtest.artifacts import RECORD_FILE
from fefat.backtest.metrics import Metrics
from fefat.config import resolve_paths
from fefat.market.engine_units import money_in_units
from fefat.market.fidelity import FidelityEra
from fefat_app.container import Container
from fefat_app.database.models import RunRow
from fefat_app.database.run_records import RunTables
from local_server import STARTED_AT, logged_in
from test_run_records import a_submission, the_run

NANOSECONDS = 1_000_000_000
KEY_OF_NO_RUN = "e" * 64


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
    assert Decimal(body["capital"]) == run.config.capital
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
    # Done means 3: the engine's own figure, on a curve cut to a tenth of its decisions.
    decisions = run.equity("5m").get_column("equity").drop_nulls().len()
    assert decisions > 500

    body = client.get(f"/v1/runs/{run.hash}/equity", params={"max_points": 90}).json()

    assert len(body["time"]) <= 90
    assert len(body["time"]) == len(body["equity"]) == len(body["drawdown"])
    assert max(body["drawdown"]) == float(run.metrics.drawdown.max_drawdown)


@pytest.mark.parametrize("max_points", [4, 10_001])
def test_points_out_of_bounds_are_refused(client: TestClient, run: Run, max_points: int) -> None:
    answer = client.get(f"/v1/runs/{run.hash}/equity", params={"max_points": max_points})

    assert answer.status_code == 422


def test_the_distributions_are_the_sdks(client: TestClient, run: Run) -> None:
    body = client.get(f"/v1/runs/{run.hash}/distribution").json()

    assert TradeDistributions.model_validate(body) == ff.backtest.trade_distributions(run.trades)
    assert sum(body["pnl"]["trades"]) == run.metrics.trades.trades


@pytest.mark.parametrize("result", ["stats", "equity", "distribution"])
def test_an_unknown_run_answers_404(client: TestClient, run: Run, result: str) -> None:
    assert run.hash != KEY_OF_NO_RUN

    answer = client.get(f"/v1/runs/{KEY_OF_NO_RUN}/{result}")

    assert answer.status_code == 404
    assert "names none" in answer.json()["detail"]


@pytest.mark.parametrize("result", ["stats", "equity", "distribution"])
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


@pytest.mark.parametrize("result", ["stats", "equity", "distribution"])
def test_a_folder_that_is_gone_says_so(client: TestClient, run: Run, result: str) -> None:
    shutil.rmtree(run.folder)

    answer = client.get(f"/v1/runs/{run.hash}/{result}")

    assert answer.status_code == 409
    assert "is gone" in answer.json()["detail"]
    assert "Run the backtest again" in answer.json()["detail"]


@pytest.mark.parametrize("result", ["stats", "equity", "distribution"])
def test_a_run_another_engine_saved_is_refused_in_the_engines_words(
    client: TestClient, run: Run, result: str
) -> None:
    written_by = run.record.versions.engine - 1
    with_record(run, lambda document: document["versions"].update(engine=written_by))

    answer = client.get(f"/v1/runs/{run.hash}/{result}")

    assert answer.status_code == 409
    assert f"got one of version {written_by}" in answer.json()["detail"]
    assert "run it again with this engine" in answer.json()["detail"]


def test_a_folder_copied_by_hand_is_refused_in_the_sdks_words(client: TestClient, run: Run) -> None:
    with_record(run, lambda document: document.update(run_key=KEY_OF_NO_RUN))

    answer = client.get(f"/v1/runs/{run.hash}/stats")

    assert answer.status_code == 409
    assert "copied or renamed by hand" in answer.json()["detail"]


def test_an_artifact_that_is_gone_says_so(client: TestClient, run: Run) -> None:
    (run.folder / "trades.parquet").unlink()

    answer = client.get(f"/v1/runs/{run.hash}/distribution")

    assert answer.status_code == 409
    assert "is gone" in answer.json()["detail"]


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


@pytest.mark.parametrize("result", ["stats", "equity", "distribution"])
def test_the_results_need_a_login(client: TestClient, result: str) -> None:
    assert client.get(f"/v1/runs/{KEY_OF_NO_RUN}/{result}").status_code == 401
