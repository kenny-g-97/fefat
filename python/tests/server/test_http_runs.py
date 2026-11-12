"""The runs over the API (step 5.3, `01-architecture.md` section 7), through the app's process pool
of one worker: a backtest asked for twice is one run with one job, saved once its job ends, its
folder holding its artifacts and its metrics in the index, and asked for again it is answered 200
with the same id (Done means 1); its job's stream holds its four stages in order between `running`
and `succeeded` (Done means 3); the version's code runs in the executor's runners alone, never in
the server or the pool's worker; and an unknown version, or a window that ends before it starts,
is refused."""

import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from fefat.config import resolve_paths
from fefat_app.container import Container
from local_server import logged_in
from notebook_runs import store_with
from strategy_code import ES_BREAKOUT, HYPOTHESIS
from test_http_streams import next_events

DEADLINE_SECONDS = 240
WINDOW = {"start": "2026-03-05", "end": "2026-03-09"}
ARTIFACTS = [
    "costs.parquet",
    "equity.parquet",
    "equity_daily.parquet",
    "fills.parquet",
    "log.parquet",
    "orders.parquet",
    "run.json",
    "signals.parquet",
    "trade_paths.parquet",
    "trades.parquet",
]


def noting_its_processes(processes: Path) -> str:
    """The breakout on ES, whose code notes each process that runs it in `processes`."""
    noted = (
        "import os\n"
        "from pathlib import Path\n\n"
        f"with Path({str(processes)!r}).open('a', encoding='utf-8') as noted:\n"
        "    noted.write(f'{os.getpid()}\\n')\n\n"
    )
    return noted + ES_BREAKOUT


def ended(client: TestClient, run_id: str) -> dict[str, Any]:
    """The run once its job has ended."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    while True:
        run = client.get(f"/v1/runs/{run_id}").json()
        if run["status"] not in ("queued", "running"):
            return run
        assert time.monotonic() < deadline, f"Expected the run to end, got {run['status']}."
        time.sleep(0.2)


def test_a_run_asked_for_twice_is_one_run_whose_stages_reach_its_stream(
    client: TestClient, container: Container, tmp_path: Path
) -> None:
    store_with("ohlcv-1m")
    csrf = logged_in(client, container)
    processes = tmp_path / "processes"
    code = noting_its_processes(processes)
    saved = client.post(
        "/v1/strategies",
        json={"name": "breakout", "code": code, "hypothesis": HYPOTHESIS},
        headers=csrf,
    )
    body = {"strategy_version_id": saved.json()["id"], **WINDOW}

    first = client.post("/v1/runs", json=body, headers=csrf)
    second = client.post("/v1/runs", json=body, headers=csrf)
    run = ended(client, first.json()["id"])
    third = client.post("/v1/runs", json=body, headers=csrf)

    # Done means 1: one id, one job, the artifacts on disk, the metrics in the index.
    assert (saved.status_code, first.status_code, third.status_code) == (201, 202, 200)
    assert second.status_code in (200, 202)
    assert first.json()["id"] == second.json()["id"] == third.json()["id"] == run["id"]
    jobs = [job for job in client.get("/v1/jobs").json() if job["kind"] == "backtest"]
    assert [job["id"] for job in jobs] == [run["job_id"]]
    assert (run["status"], run["settings"]["provider"]) == ("succeeded", "synthetic")
    assert run["metrics"]["trades"]["trades"] > 0
    folder = resolve_paths(os.environ).runs_dir / run["run_key"]
    assert sorted(path.name for path in folder.iterdir()) == ARTIFACTS
    # Done means 3: the stages of the run, in order, between its job's start and its end.
    with client.stream("GET", f"/v1/streams/job:{run['job_id']}") as stream:
        events = [json.loads(event["data"]) for event in next_events(stream.iter_lines(), 7)]
    assert [(each.get("status"), each.get("percent"), each.get("message")) for each in events] == [
        ("queued", None, None),
        ("running", None, None),
        (None, 30.0, "Loaded the data"),
        (None, 50.0, "Computed the features and signals"),
        (None, 60.0, "Running the engine"),
        (None, 100.0, "Wrote the artifacts"),
        ("succeeded", None, None),
    ]
    # The trader's code ran in the executor's runners alone, the save's, the three lookups', and
    # the backtest's, never in the server's process or the pool's worker.
    noted = [int(line) for line in processes.read_text(encoding="utf-8").split()]
    worker = client.get(f"/v1/jobs/{run['job_id']}").json()["worker_pid"]
    assert len(noted) == 5
    assert os.getpid() not in noted
    assert worker not in noted


def test_an_unknown_version_and_a_window_ending_before_it_starts_are_refused(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)

    unknown = client.post("/v1/runs", json={"strategy_version_id": "none", **WINDOW}, headers=csrf)
    backwards = client.post(
        "/v1/runs",
        json={"strategy_version_id": "none", "start": "2026-03-09", "end": "2026-03-05"},
        headers=csrf,
    )
    missing = client.get("/v1/runs/none")

    assert (unknown.status_code, backwards.status_code, missing.status_code) == (404, 422, 404)
    assert "Expected the id of a saved strategy version" in unknown.json()["detail"]
    assert client.get("/v1/runs").json() == []
