"""`POST /v1/runs/{run}/reproduce` of step 5.10 (D-93, D-126): a saved run made again as a
`reproduce` job, which a worker of the pool runs through the executor. Done means 2, the synthetic
run: the breakout's run on the fixtures' minute bars reproduces with its trades' hash matched,
leaving no folder and indexing nothing. Data changed since the run, or deleted since, is refused as
the job's answer, in words that name no folder of this PC (D-99, D-80), as is an OS error's file
name, its backslashes doubled; a run of a strategy built in a notebook, an unknown run, and a
request without the session's CSRF header are refused, and queue no job."""

import os
import shutil
from pathlib import Path

import fefat_engine
import pytest
from fastapi.testclient import TestClient

import fefat as ff
from fefat.backtest import Run
from fefat.config import resolve_paths
from fefat_app.container import Container
from fefat_app.jobs.trade_explanations import without_folders
from fefat_app.reproductions import REPRODUCTIONS_FOLDER
from local_server import logged_in
from notebook_runs import breakout, store_with
from test_http_trade_review import finished
from test_http_trades import csrf
from test_run_records import the_run

RUN_WINDOW = ("2026-03-05", "2026-03-09")


@pytest.fixture
def run(client: TestClient, container: Container, breakout_workspace: Path) -> Run:
    """The saved breakout, logged in and listed, so that the index holds its row, beside the
    1-minute bars it read."""
    logged_in(client, container)
    shutil.copytree(breakout_workspace, resolve_paths(os.environ).workspace_dir)
    store_with("ohlcv-1m")
    assert client.get("/v1/runs").status_code == 200
    return the_run()


def test_a_saved_run_reproduced_matches_its_trades_hash_and_indexes_nothing(
    client: TestClient, run: Run
) -> None:
    # Done means 2, the synthetic run.
    started = client.post(f"/v1/runs/{run.hash}/reproduce", headers=csrf(client))
    ended = finished(client, started.json()["id"])

    assert started.status_code == 202
    assert (started.json()["kind"], started.json()["payload"]["reproduces"]) == (
        "reproduce",
        run.hash,
    )
    assert (ended["status"], ended["error"]) == ("succeeded", None)
    assert ended["result"] == {
        "verdict": "matched",
        "trades_hash": fefat_engine.table_hash(run.trades),
    }
    paths = resolve_paths(os.environ)
    assert not (paths.cache_dir / REPRODUCTIONS_FOLDER / run.hash).exists()
    assert [each["run_key"] for each in client.get("/v1/runs").json()["runs"]] == [run.hash]


def test_data_changed_since_the_run_is_refused_in_words_that_name_no_folder(
    client: TestClient, run: Run
) -> None:
    paths = resolve_paths(os.environ)
    bars = paths.data_dir / "synthetic" / "ohlcv-1m" / "root=ES"
    part = bars / "contract=ESH2026" / "month=2026-03" / "part.parquet"
    part.write_bytes(part.read_bytes() + b"changed")

    started = client.post(f"/v1/runs/{run.hash}/reproduce", headers=csrf(client))
    ended = finished(client, started.json()["id"])

    assert (ended["status"], ended["result"]["verdict"]) == ("succeeded", "refused")
    reason = ended["result"]["reason"]
    assert "the data changed since the run. By the files' times, written since" in reason
    assert "synthetic/ohlcv-1m/root=ES/contract=ESH2026/month=2026-03/part.parquet" in reason
    assert str(paths.home) not in reason
    assert str(paths.data_dir) not in reason


def test_data_deleted_since_the_run_is_refused_naming_the_data_folder_in_words(
    client: TestClient, run: Run
) -> None:
    # The scrub of the job's answer (D-80): the store's refusal names its folder, which the job
    # names in words.
    paths = resolve_paths(os.environ)
    shutil.rmtree(paths.data_dir / "synthetic" / "ohlcv-1m")

    started = client.post(f"/v1/runs/{run.hash}/reproduce", headers=csrf(client))
    ended = finished(client, started.json()["id"])

    assert (ended["status"], ended["result"]["verdict"]) == ("succeeded", "refused")
    assert "its data was deleted since the run" in ended["result"]["reason"]
    assert ended["result"]["reason"].endswith("The store read: your data folder.")


def test_an_os_errors_file_name_is_named_in_words_as_its_backslashes_double() -> None:
    # An OSError writes its file name with repr, so that on Windows each backslash is doubled.
    paths = resolve_paths(os.environ)
    key = "e" * 64
    missing = FileNotFoundError(
        2, "No such file or directory", str(paths.runs_dir / key / "run.json")
    )
    data = FileNotFoundError(2, "No such file or directory", str(paths.data_dir / "x.parquet"))

    assert f"run {key[:12]}" in without_folders(str(missing), paths, key)
    assert "your data folder" in without_folders(str(data), paths, key)


def test_a_notebook_run_an_unknown_run_and_an_unsigned_request_are_refused(
    client: TestClient, run: Run
) -> None:
    notebook = ff.backtest.run(breakout(), *RUN_WINDOW)
    assert client.get("/v1/runs").status_code == 200

    refused = client.post(f"/v1/runs/{notebook.hash}/reproduce", headers=csrf(client))
    unknown = client.post(f"/v1/runs/{'e' * 64}/reproduce", headers=csrf(client))
    unsigned = client.post(f"/v1/runs/{run.hash}/reproduce")

    assert (refused.status_code, unknown.status_code, unsigned.status_code) == (409, 404, 403)
    assert "of a strategy built in a notebook" in refused.json()["detail"]
    assert [job for job in client.get("/v1/jobs").json() if job["kind"] == "reproduce"] == []
