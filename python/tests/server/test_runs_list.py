"""The runs' list of step 5.6 (D-113): pages newest first by a keyset that holds through runs of
one instant; the filters by strategy, status, and no saved version; a run read and cancelled by its
id or its run key; the run folders no row holds indexed as the lists load, a notebook's with the
version it names, never while a backtest is under way, whose folder it could be; what a run would
read before anything runs; and a stress, the same run at more ticks of slippage."""

import json
import os
import shutil
from base64 import urlsafe_b64encode
from datetime import timedelta
from pathlib import Path
from typing import Any, NoReturn

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

import fefat as ff
from fefat.config import resolve_paths
from fefat_app.container import Container
from fefat_app.database import workspace_index
from fefat_app.database.job_records import JobTables
from fefat_app.database.library_index import LibraryTables
from fefat_app.database.run_records import RunTables
from fefat_app.http.openapi_document import openapi_document
from fefat_app.job_models import JobStatus
from fefat_app.runs import (
    IndexedRun,
    RunCursorError,
    SavedRun,
    SavedRunWithMetrics,
    SubmittedRun,
)
from local_server import STARTED_AT, logged_in
from notebook_runs import breakout, store_with
from strategy_code import ES_BREAKOUT, HYPOTHESIS
from test_run_records import a_submission, the_run

KEY_OF_NO_RUN = "e" * 64


@pytest.fixture
def library(breakout_workspace: Path, engine: Engine) -> LibraryTables:
    """The index over the test's home holding the saved breakout and its run, neither indexed."""
    paths = resolve_paths(os.environ)
    shutil.copytree(breakout_workspace, paths.workspace_dir)
    return LibraryTables(engine, paths)


@pytest.fixture
def records(library: LibraryTables, engine: Engine) -> RunTables:
    """The runs' records over the home of `library`, its versions indexed."""
    library.refresh()
    return RunTables(engine, resolve_paths(os.environ))


def page_of(
    records: RunTables,
    *,
    strategy: str | None = None,
    versioned: bool | None = None,
    status: JobStatus | None = None,
) -> tuple[IndexedRun, ...]:
    found = records.page(
        strategy=strategy, versioned=versioned, status=status, cursor=None, limit=100
    )
    assert found.next_cursor is None
    return found.runs


def ids(runs: tuple[IndexedRun, ...]) -> set[str]:
    return {run.id for run in runs}


def test_the_list_pages_through_runs_of_one_day_and_one_instant(
    records: RunTables, engine: Engine
) -> None:
    # Three runs share an instant, and all five a day: a comparison of row values would bind the
    # cursor's instant in SQLite's own form and skip the rest of its day (the plan's design pass).
    hours = (0, 0, 0, 1, 2)
    made = [
        records.submitted(a_submission(engine, None), 3, STARTED_AT + timedelta(hours=hour)).run
        for hour in hours
    ]
    newest_first = sorted(made, key=lambda run: (run.created_at, run.id), reverse=True)

    walked: list[IndexedRun] = []
    cursor = None
    pages = 0
    while pages == 0 or cursor is not None:
        page = records.page(strategy=None, versioned=None, status=None, cursor=cursor, limit=2)
        walked.extend(page.runs)
        cursor = page.next_cursor
        pages += 1

    assert pages == 3
    assert [run.id for run in walked] == [run.id for run in newest_first]


def test_a_cursor_no_page_gave_is_refused(records: RunTables) -> None:
    before_any_instant = urlsafe_b64encode(b"0001-01-01T00:00:00+14:00|id").decode()
    for cursor in (
        "not base64 at all",
        "bm90IGEgY3Vyc29y",
        "MjAyNi0wMy0wNnxpZA==",
        before_any_instant,
    ):
        with pytest.raises(RunCursorError, match="Expected a cursor the list of runs gave"):
            records.page(strategy=None, versioned=None, status=None, cursor=cursor, limit=2)


def test_the_list_filters_by_strategy_status_and_no_saved_version(
    records: RunTables, engine: Engine
) -> None:
    saved = records.saved(the_run().hash)
    queued = records.submitted(a_submission(engine, None), 3, STARTED_AT).run
    cancelled = records.submitted(a_submission(engine, None), 3, STARTED_AT).run
    JobTables(engine).cancel_queued(cancelled.job_id, STARTED_AT)
    store_with("ohlcv-1m")
    from_a_notebook = records.saved(ff.backtest.run(breakout(), "2026-03-05", "2026-03-09").hash)

    assert ids(page_of(records)) == {saved.id, from_a_notebook.id, queued.id, cancelled.id}
    assert ids(page_of(records, strategy="breakout")) == {saved.id, queued.id, cancelled.id}
    assert ids(page_of(records, strategy="another")) == set()
    assert ids(page_of(records, versioned=False)) == {from_a_notebook.id}
    assert ids(page_of(records, status=JobStatus.SUCCEEDED)) == {saved.id, from_a_notebook.id}
    assert ids(page_of(records, status=JobStatus.QUEUED)) == {queued.id}
    assert ids(page_of(records, status=JobStatus.CANCELLED)) == {cancelled.id}
    assert ids(page_of(records, strategy="breakout", status=JobStatus.SUCCEEDED)) == {saved.id}


def test_a_listed_run_carries_its_jobs_progress_or_its_key_metrics(
    records: RunTables, engine: Engine
) -> None:
    run = the_run()
    saved = records.saved(run.hash)
    made = records.submitted(a_submission(engine, None), 3, STARTED_AT + timedelta(days=9)).run
    job_records = JobTables(engine)
    job_records.start(made.job_id, 4242, STARTED_AT, STARTED_AT)
    job_records.advance(made.job_id, 4242, 42.0, "Computed the features", {})

    listed = page_of(records)

    (submitted,) = [each for each in listed if isinstance(each, SubmittedRun)]
    (listed_saved,) = [each for each in listed if isinstance(each, SavedRun)]
    assert (submitted.status, submitted.progress, submitted.message) == (
        JobStatus.RUNNING,
        42.0,
        "Computed the features",
    )
    assert listed_saved.key_metrics == saved.key_metrics
    assert (
        listed_saved.key_metrics.pnl,
        listed_saved.key_metrics.trades,
        listed_saved.key_metrics.max_drawdown,
        listed_saved.key_metrics.verdict,
    ) == (
        run.metrics.pnl,
        run.metrics.trades.trades,
        run.metrics.drawdown.max_drawdown,
        run.metrics.robustness.verdict,
    )


def test_a_run_is_read_by_its_id_or_its_key(records: RunTables) -> None:
    run = the_run()
    saved = records.saved(run.hash)

    by_id, by_key = records.by_id(saved.id), records.by_id(run.hash)

    assert isinstance(by_id, SavedRunWithMetrics)
    assert by_id == by_key
    assert by_id.metrics == run.metrics
    assert records.by_id(KEY_OF_NO_RUN) is None


def test_a_notebooks_run_names_the_version_a_notebook_saved(
    library: LibraryTables, engine: Engine
) -> None:
    # Neither the version nor its run was indexed: the one write indexes both, so that the run
    # names its version, which the row could not take later, once saved.
    library.index_saved_runs()

    (listed,) = page_of(RunTables(engine, resolve_paths(os.environ)))

    assert isinstance(listed, SavedRun)
    assert listed.run_key == the_run().hash
    assert listed.strategy is not None
    assert (listed.strategy.name, listed.strategy.version) == ("breakout", 1)
    assert (listed.strategy.instrument, listed.strategy.timeframe) == ("ES", "5m")


def test_a_folder_is_not_indexed_while_a_run_waits_on_its_job_even_one_asked_to_stop(
    library: LibraryTables, records: RunTables, engine: Engine
) -> None:
    # A job asked to stop once its artifacts are written still indexes its run: were the folder
    # indexed under a row of its own, the job's `saved` would delete the submission's row.
    submitted = records.submitted(a_submission(engine), 3, STARTED_AT)
    job_id = submitted.run.job_id
    jobs = JobTables(engine)
    jobs.start(job_id, 4242, STARTED_AT, STARTED_AT)
    jobs.request_cancel(job_id, STARTED_AT)

    library.index_saved_runs()

    assert ids(page_of(records)) == {submitted.run.id}
    assert records.saved(the_run().hash, job_id=job_id).id == submitted.run.id


def test_one_folder_indexed_twice_adds_one_row(library: LibraryTables, engine: Engine) -> None:
    library.index_saved_runs()
    library.index_saved_runs()

    assert len(page_of(RunTables(engine, resolve_paths(os.environ)))) == 1


def test_a_folder_the_sdk_refuses_is_passed_over(library: LibraryTables, engine: Engine) -> None:
    runs_dir = resolve_paths(os.environ).runs_dir
    run = the_run()
    shutil.copytree(run.folder, runs_dir / KEY_OF_NO_RUN)
    unreadable = runs_dir / ("d" * 64)
    unreadable.mkdir()
    (unreadable / "run.json").write_text("{}", encoding="utf-8")

    library.index_saved_runs()
    (unreadable / "run.json").write_text("not read again", encoding="utf-8")
    library.index_saved_runs()

    (listed,) = page_of(RunTables(engine, resolve_paths(os.environ)))
    assert isinstance(listed, SavedRun)
    assert listed.run_key == run.hash


def test_a_folder_that_cannot_be_opened_is_read_by_the_next_list(
    library: LibraryTables, engine: Engine
) -> None:
    # An antivirus or a notebook can hold a run's file for a moment: no list fails on it, and
    # the folder is not given up, as one the SDK refuses is.
    def held_open(runs_dir: Path, run_key: str) -> NoReturn:
        raise PermissionError(f"Another program holds {run_key} in {runs_dir}.")

    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(workspace_index, "saved_run", held_open)
        library.index_saved_runs()
    records = RunTables(engine, resolve_paths(os.environ))
    assert page_of(records) == ()

    library.index_saved_runs()

    (listed,) = page_of(records)
    assert isinstance(listed, SavedRun)
    assert listed.run_key == the_run().hash


def test_only_a_lists_first_page_looks_for_new_folders(
    client: TestClient,
    container: Container,
    breakout_workspace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged_in(client, container)
    shutil.copytree(breakout_workspace, resolve_paths(os.environ).workspace_dir)
    looked: list[LibraryTables] = []

    def noted(index: LibraryTables) -> None:
        looked.append(index)

    monkeypatch.setattr(LibraryTables, "index_saved_runs", noted)
    next_page = urlsafe_b64encode(b"2026-03-06T00:00:00+00:00|id").decode()

    assert client.get("/v1/runs", params={"cursor": next_page}).status_code == 200
    assert looked == []

    assert client.get("/v1/runs").status_code == 200
    assert len(looked) == 1


def test_the_lists_answer_a_notebooks_run_without_an_import(
    client: TestClient, container: Container, breakout_workspace: Path
) -> None:
    logged_in(client, container)
    shutil.copytree(breakout_workspace, resolve_paths(os.environ).workspace_dir)
    run = the_run()

    answered = client.get("/v1/runs").json()

    assert answered["next_cursor"] is None
    (listed,) = answered["runs"]
    assert (listed["state"], listed["run_key"], listed["status"]) == (
        "saved",
        run.hash,
        "succeeded",
    )
    assert listed["key_metrics"]["trades"] == run.metrics.trades.trades
    assert "metrics" not in listed
    assert client.get(f"/v1/runs/{run.hash}").json()["id"] == listed["id"]


def test_a_cursor_the_list_did_not_give_is_a_bad_request(
    client: TestClient, container: Container
) -> None:
    logged_in(client, container)

    refused = client.get("/v1/runs", params={"cursor": "nonsense"})

    assert refused.status_code == 400
    assert "Expected a cursor" in refused.json()["detail"]


def test_a_saved_run_is_cancelled_as_it_is_by_its_key(
    client: TestClient, container: Container, breakout_workspace: Path
) -> None:
    csrf = logged_in(client, container)
    shutil.copytree(breakout_workspace, resolve_paths(os.environ).workspace_dir)
    run = the_run()
    client.get("/v1/runs")

    answered = client.post(f"/v1/runs/{run.hash}/cancel", headers=csrf)

    assert (answered.status_code, answered.json()["run_key"]) == (200, run.hash)
    assert client.get(f"/v1/runs/{KEY_OF_NO_RUN}").status_code == 404


def test_an_estimate_names_what_a_run_would_read(client: TestClient, container: Container) -> None:
    csrf = logged_in(client, container)
    store_with("ohlcv-1m")
    saved = client.post(
        "/v1/strategies",
        json={"name": "breakout", "code": ES_BREAKOUT, "hypothesis": HYPOTHESIS},
        headers=csrf,
    ).json()
    body = {"strategy_version_id": saved["id"]}

    answered = client.post("/v1/runs/estimate", json=body, headers=csrf)
    outside = client.post(
        "/v1/runs/estimate",
        json={**body, "start": "2026-04-01", "end": "2026-04-02"},
        headers=csrf,
    )
    backwards = client.post(
        "/v1/runs/estimate",
        json={**body, "start": "2026-03-09", "end": "2026-03-05"},
        headers=csrf,
    )
    wrong_provider = client.post(
        "/v1/runs/estimate", json={**body, "settings": {"provider": "nobody"}}, headers=csrf
    )
    unknown = client.post("/v1/runs/estimate", json={"strategy_version_id": "none"}, headers=csrf)
    no_contract = client.post(
        "/v1/runs/estimate", json={**body, "settings": {"contract": "nonsense"}}, headers=csrf
    )

    estimate = answered.json()
    assert (answered.status_code, estimate["state"]) == (200, "estimated")
    assert (estimate["instrument"], estimate["timeframe"]) == ("ES", "5m")
    assert estimate["providers"] == ["synthetic"]
    assert estimate["contracts"] == ["ESH2026", "ESM2026"]
    assert estimate["levels"] == ["1m"]
    assert estimate["held"] == {"start": "2026-03-06", "end": "2026-03-09"}
    assert estimate["window"] == estimate["held"]
    assert (estimate["sessions"], estimate["ticks"]) == (2, 0)
    assert estimate["bars"] > 0
    assert estimate["settings"]["provider"] == "synthetic"
    assert (outside.json()["window"], outside.json()["sessions"]) == (None, 0)
    assert (
        backwards.status_code,
        no_contract.status_code,
        wrong_provider.status_code,
        unknown.status_code,
    ) == (422, 422, 400, 404)
    assert "Expected a provider of ES" in wrong_provider.json()["detail"]


def test_an_instrument_the_store_does_not_hold_has_no_estimate(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)
    store_with("ohlcv-1m")
    saved = client.post(
        "/v1/strategies",
        json={
            "name": "not_held",
            "code": ES_BREAKOUT.replace('instrument="ES"', 'instrument="MES"'),
            "hypothesis": HYPOTHESIS,
        },
        headers=csrf,
    ).json()

    answered = client.post(
        "/v1/runs/estimate", json={"strategy_version_id": saved["id"]}, headers=csrf
    )

    assert answered.json() == {"state": "no_data", "instrument": "MES", "timeframe": "5m"}


def test_the_document_tells_a_runs_states_apart_by_state() -> None:
    document: dict[str, Any] = json.loads(json.dumps(openapi_document()))
    one = document["paths"]["/v1/runs/{run}"]["get"]["responses"]["200"]
    schema = one["content"]["application/json"]["schema"]

    assert schema["discriminator"]["propertyName"] == "state"
    assert sorted(each["$ref"].rsplit("/", 1)[1] for each in schema["oneOf"]) == [
        "SavedRunWithMetrics",
        "SubmittedRun",
    ]
