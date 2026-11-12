"""A backtest as a job (step 5.3, `01-architecture.md` section 6): a worker runs the version's
backtest through an executor of its own, each stage a `progress` event of the job's stream, then
indexes the run folder into the run's row; the run equals the one a notebook makes of the same
version and settings, its trades byte for byte (Done means 2); a strategy that fails on real bars
fails its run with its own words; and a run asked to stop ends `cancelled` within seconds, its
runner stopped and no folder saved. Run in this process, as `test_job_executions` runs a job."""

import os
import shutil
import threading
import time
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine

import fefat as ff
from fefat.backtest import RunConfig, saved_runs_in
from fefat.backtest.requests import looked_up
from fefat.config import resolve_paths
from fefat_app.database.job_records import JobTables
from fefat_app.database.library_index import LibraryTables
from fefat_app.database.run_records import RunTables
from fefat_app.execution import (
    BacktestOutput,
    BacktestSpec,
    ExecutionLimits,
    ExecutionProgress,
    ExecutionResult,
    ExecutionSpec,
    ExecutionSucceeded,
    ProgressReport,
    StopCheck,
    keep_running,
)
from fefat_app.job_models import JobStatus, job_stream
from fefat_app.jobs.backtests import run_backtest
from fefat_app.jobs.progress import JobCancelledError, JobProgress
from fefat_app.jobs.worker import JobTimings, run_job
from fefat_app.runs import NewRun, RequestedRun, Submitted
from local_server import STARTED_AT, running_runners
from notebook_runs import store_with
from strategy_code import ES_BREAKOUT, HYPOTHESIS

WINDOW = (date(2026, 3, 5), date(2026, 3, 9))
LIMITS = ExecutionLimits(timeout_seconds=300, memory_bytes=8 * 1024**3)
REFUSING = """\
import polars as pl

import fefat as ff


def refused(closes: pl.Series) -> pl.Series:
    if closes.len() > 0:
        raise ValueError("this strategy refuses real bars")
    return closes


def strategy() -> ff.SignalStrategy:
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={"seen": pl.col("close").map_batches(refused, return_dtype=pl.Int64)},
        long_entry=pl.col("seen") > 0,
        short_entry=pl.lit(False),
        execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(1)),
    )
"""
"""A strategy whose slot fails on real bars alone: it builds on bars without rows, as a save
builds it, and keys no request, as an expression that calls Python keys none."""
SLEEPING = REFUSING.replace(
    'raise ValueError("this strategy refuses real bars")', "time.sleep(120)"
).replace("import polars as pl\n", "import time\n\nimport polars as pl\n", 1)
"""The same, sleeping on real bars for two minutes."""
DEADLINE_SECONDS = 120


def submitted(engine: Engine, name: str, code: str) -> Submitted:
    """A run of version 1 of the strategy `name` of `code`, saved and indexed, submitted with its
    queued `backtest` job."""
    paths = resolve_paths(os.environ)
    version = ff.strategy.save(name, code, hypothesis=HYPOTHESIS)
    library = LibraryTables(engine, paths)
    library.refresh()
    (indexed,) = library.strategies()
    run = RequestedRun(
        strategy=name,
        version=1,
        hash=version.hash,
        parameters={},
        start=WINDOW[0],
        end=WINDOW[1],
        settings=RunConfig(),
    )
    lookup = looked_up(version.strategy(), *WINDOW, RunConfig(), paths)
    new = NewRun(
        strategy_version_id=indexed.versions[0].id,
        payload=BacktestSpec(run=run, limits=LIMITS).model_dump(mode="json"),
        parameters={},
        start=WINDOW[0],
        end=WINDOW[1],
        settings=lookup.config,
        request_key=None if lookup.request is None else lookup.request.key(),
    )
    return RunTables(engine, paths).submitted(new, 3, STARTED_AT)


def test_a_backtest_job_saves_the_run_a_notebook_makes_of_its_version(
    engine: Engine, job_records: JobTables, tmp_path: Path
) -> None:
    # Done means 2 and 3: the job's run is the notebook's, and its stages reach the stream.
    store_with("ohlcv-1m")
    made = submitted(engine, "breakout", ES_BREAKOUT)
    job_id = made.queued_job_id or "none"

    run_job(job_id, resolve_paths(os.environ), JobTimings())

    job = job_records.by_id(job_id)
    run = RunTables(engine, resolve_paths(os.environ)).by_id(made.run.id)
    assert job is not None
    assert run is not None
    assert (job.status, run.status, run.metrics is not None) == (
        JobStatus.SUCCEEDED,
        JobStatus.SUCCEEDED,
        True,
    )
    assert job.result == {"run_id": made.run.id, "run_key": run.run_key}
    events = job_records.events_after(job_stream(job_id), 0, 100)
    assert [(event.said.get("status"), event.said.get("percent")) for event in events] == [
        ("queued", None),
        ("running", None),
        (None, 30.0),
        (None, 50.0),
        (None, 60.0),
        (None, 100.0),
        ("succeeded", None),
    ]
    with pytest.MonkeyPatch.context() as notebook:
        notebook.setenv("FEFAT_HOME", str(tmp_path / "a notebook's home"))
        version = ff.strategy.save("breakout", ES_BREAKOUT, hypothesis=HYPOTHESIS)
        written = ff.backtest.run(ff.strategy.load("breakout", version.version).strategy(), *WINDOW)
    (saved,) = saved_runs_in(resolve_paths(os.environ).runs_dir)
    assert written.hash == saved.hash == run.run_key
    assert (written.folder / "trades.parquet").read_bytes() == (
        saved.folder / "trades.parquet"
    ).read_bytes()


def test_a_strategy_that_fails_on_real_bars_fails_its_run_with_its_words(
    engine: Engine,
) -> None:
    store_with("ohlcv-1m")
    made = submitted(engine, "refusing", REFUSING)

    run_job(made.queued_job_id or "none", resolve_paths(os.environ), JobTimings())

    run = RunTables(engine, resolve_paths(os.environ)).by_id(made.run.id)
    assert run is not None
    assert (run.status, run.run_key) == (JobStatus.FAILED, None)
    assert run.error is not None
    assert "ValueError: this strategy refuses real bars" in run.error
    assert saved_runs_in(resolve_paths(os.environ).runs_dir) == ()


def test_a_backtest_asked_to_stop_ends_cancelled_with_its_runner(
    engine: Engine, job_records: JobTables
) -> None:
    store_with("ohlcv-1m")
    made = submitted(engine, "sleeping", SLEEPING)
    job_id = made.queued_job_id or "none"
    worker = threading.Thread(
        target=run_job, args=(job_id, resolve_paths(os.environ), JobTimings())
    )
    worker.start()
    deadline = time.monotonic() + DEADLINE_SECONDS
    while _progress_of(job_records, job_id) < 30:
        assert time.monotonic() < deadline, "Expected the backtest to load its data."
        time.sleep(0.05)

    job_records.request_cancel(job_id, datetime.now(UTC))
    began = time.monotonic()
    worker.join(DEADLINE_SECONDS)

    run = RunTables(engine, resolve_paths(os.environ)).by_id(made.run.id)
    assert run is not None
    assert run.status == JobStatus.CANCELLED
    assert time.monotonic() - began < 5
    assert running_runners() == []
    assert saved_runs_in(resolve_paths(os.environ).runs_dir) == ()


def _progress_of(job_records: JobTables, job_id: str) -> float:
    now = job_records.by_id(job_id)
    assert now is not None
    return now.progress


class AskedToStopAt:
    """An executor whose backtest reports a stage once its job was asked to stop, then lets a
    second pass, and answers the run saved under `run_key`."""

    def __init__(self, records: JobTables, job_id: str, run_key: str, percent: float) -> None:
        self.records, self.job_id, self.run_key, self.percent = records, job_id, run_key, percent

    def run(
        self, spec: ExecutionSpec, report: ProgressReport, check: StopCheck = keep_running
    ) -> ExecutionResult:
        self.records.request_cancel(self.job_id, STARTED_AT)
        report(ExecutionProgress(percent=self.percent, message="a stage", details={}))
        check()
        return ExecutionSucceeded(output=BacktestOutput(run_key=self.run_key))

    def close(self) -> None:
        """Nothing to end."""


def a_running_backtest(
    engine: Engine, workspace: Path
) -> tuple[str, dict[str, object], str, RunTables]:
    """The job of a run of the saved breakout, started by the worker 4242, with its payload, the
    key of the run the workspace holds saved, and the runs' records."""
    paths = resolve_paths(os.environ)
    shutil.copytree(workspace, paths.workspace_dir)
    LibraryTables(engine, paths).refresh()
    (saved,) = saved_runs_in(paths.runs_dir)
    runs = RunTables(engine, paths)
    (strategy,) = LibraryTables(engine, paths).strategies()
    version = strategy.versions[0]
    run = RequestedRun(
        strategy="breakout",
        version=1,
        hash=version.hash,
        parameters={},
        start=WINDOW[0],
        end=WINDOW[1],
        settings=RunConfig(),
    )
    payload = BacktestSpec(run=run, limits=LIMITS).model_dump(mode="json")
    new = NewRun(
        strategy_version_id=version.id,
        payload=payload,
        parameters={},
        start=WINDOW[0],
        end=WINDOW[1],
        settings=saved.config,
        request_key=None,
    )
    job_id = runs.submitted(new, 3, STARTED_AT).queued_job_id or "none"
    JobTables(engine).start(job_id, 4242, STARTED_AT, STARTED_AT)
    return job_id, payload, saved.hash, runs


def test_a_stop_asked_once_the_artifacts_are_written_leaves_the_run_saved(
    engine: Engine, job_records: JobTables, breakout_workspace: Path
) -> None:
    # Step 5.3 (its step review): the run is saved by its last report, which a request to stop
    # can no longer undo; the job indexes it and succeeds, rather than ending cancelled while
    # its folder stays unindexed.
    job_id, payload, run_key, runs = a_running_backtest(engine, breakout_workspace)
    executor = AskedToStopAt(job_records, job_id, run_key, 100.0)

    result = run_backtest(executor, runs, payload, JobProgress(job_records, job_id, 4242))

    run = runs.by_id(str(result["run_id"]))
    assert run is not None
    assert (result["run_key"], run.status) == (run_key, JobStatus.SUCCEEDED)


def test_a_stop_asked_before_the_artifacts_are_written_stops_the_backtest(
    engine: Engine, job_records: JobTables, breakout_workspace: Path
) -> None:
    job_id, payload, run_key, runs = a_running_backtest(engine, breakout_workspace)
    executor = AskedToStopAt(job_records, job_id, run_key, 60.0)

    with pytest.raises(JobCancelledError):
        run_backtest(executor, runs, payload, JobProgress(job_records, job_id, 4242))
