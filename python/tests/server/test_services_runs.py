"""The runs' service (step 5.3, D-93), with an executor that answers each lookup as told and a
dispatcher that runs nothing: a submission looks its run up in the executor, as the version's
file is indexed, and queues the run's job once, a second submission of the same request being the
first while its job waits; a run found saved is answered saved, the row waiting on its request
being that run; a run asked to stop is not the one a new submission waits on; and an unknown
version, a version file the index cannot follow, and code the SDK refuses are refused."""

import os
import shutil
import threading
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine

from fefat.backtest import RunConfig, saved_runs_in
from fefat.config import resolve_paths
from fefat.market.store import Store
from fefat.reference.settings import SlippageTicks
from fefat_app.database.job_records import JobTables
from fefat_app.database.library_index import LibraryTables
from fefat_app.database.run_records import RunTables
from fefat_app.execution import (
    BacktestSpec,
    ExecutionResult,
    ExecutionSpec,
    ExecutionSucceeded,
    ProgressReport,
    RefusedCode,
    RunLookupOutput,
    RunLookupSpec,
    StopCheck,
    keep_running,
)
from fefat_app.job_models import Job, JobKind, JobStatus
from fefat_app.library import LibraryRefusedError
from fefat_app.runs import RequestedRun, RunToMake, SavedRun, SavedRunFound, SubmittedRun
from fefat_app.services.catalog import MarketCatalog
from fefat_app.services.code_runs import BACKTEST_LIMITS, LIBRARY_LIMITS, CodeRefusedError
from fefat_app.services.job_reruns import JobNotRunAgainError, run_again
from fefat_app.services.jobs import Jobs
from fefat_app.services.runs import RunAsked, Runs, RunsAsked
from fefat_app.services.strategies import NoSuchStrategyError
from local_server import STARTED_AT, RecordingDispatcher, SettableClock

REQUEST = "c" * 64
WINDOW = (date(2026, 3, 5), date(2026, 3, 9))


class LookingUp:
    """An executor whose every lookup answers `answer`, keeping the specs it was given."""

    def __init__(self, answer: SavedRunFound | RunToMake | RefusedCode) -> None:
        self.answer = answer
        self.specs: list[ExecutionSpec] = []

    def run(
        self, spec: ExecutionSpec, report: ProgressReport, check: StopCheck = keep_running
    ) -> ExecutionResult:
        self.specs.append(spec)
        return ExecutionSucceeded(output=RunLookupOutput(answer=self.answer))

    def close(self) -> None:
        """Nothing to end."""


@pytest.fixture
def workspace(breakout_workspace: Path, engine: Engine) -> LibraryTables:
    """The test's home holding the saved breakout and its run, its library indexed."""
    paths = resolve_paths(os.environ)
    shutil.copytree(breakout_workspace, paths.workspace_dir)
    library = LibraryTables(engine, paths)
    library.refresh()
    return library


def runs_over(
    engine: Engine, library: LibraryTables, executor: LookingUp, dispatcher: RecordingDispatcher
) -> Runs:
    paths = resolve_paths(os.environ)
    clock = SettableClock(STARTED_AT)
    jobs = Jobs(JobTables(engine), dispatcher, clock)
    return Runs(RunTables(engine, paths), library, executor, jobs, paths, clock)


def asked(library: LibraryTables, **parameters: int) -> RunAsked:
    (strategy,) = library.strategies()
    return RunAsked(
        strategy_version_id=strategy.versions[0].id,
        parameters=dict(parameters),
        start=WINDOW[0],
        end=WINDOW[1],
        settings=RunConfig(latency_ms=50),
    )


def the_saved_key() -> str:
    (run,) = saved_runs_in(resolve_paths(os.environ).runs_dir)
    return run.hash


def to_make(request_key: str | None = REQUEST) -> RunToMake:
    (run,) = saved_runs_in(resolve_paths(os.environ).runs_dir)
    return RunToMake(request_key=request_key, parameters={"lookback": 24}, settings=run.config)


def test_a_run_to_make_is_looked_up_in_the_executor_and_its_job_queued_once(
    engine: Engine, workspace: LibraryTables
) -> None:
    executor, dispatcher = LookingUp(to_make()), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)

    first = runs.submit(asked(workspace, lookback=24))
    second = runs.submit(asked(workspace, lookback=24))

    (strategy,) = workspace.strategies()
    requested = RequestedRun(
        strategy="breakout",
        version=1,
        hash=strategy.versions[0].hash,
        parameters={"lookback": 24},
        start=WINDOW[0],
        end=WINDOW[1],
        settings=RunConfig(latency_ms=50),
    )
    assert executor.specs == [RunLookupSpec(run=requested, limits=LIBRARY_LIMITS)] * 2
    assert second.id == first.id
    assert (first.status, first.parameters) == (JobStatus.QUEUED, {"lookback": 24})
    assert dispatcher.calls == [f"submit {first.job_id}"]
    job = JobTables(engine).by_id(first.job_id or "none")
    assert job is not None
    assert job.payload == BacktestSpec(run=requested, limits=BACKTEST_LIMITS).model_dump(
        mode="json"
    )


def test_a_run_found_saved_is_the_row_waiting_on_its_request(
    engine: Engine, workspace: LibraryTables
) -> None:
    # A POST that finds the run that a waiting submission's job wrote but has not yet indexed.
    executor, dispatcher = LookingUp(to_make()), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)
    waiting = runs.submit(asked(workspace))
    found = SavedRunFound(
        run_key=the_saved_key(),
        request_key=REQUEST,
        parameters={"lookback": 24},
        settings=to_make().settings,
    )
    executor.answer = found

    saved = runs.submit(asked(workspace))

    assert isinstance(saved, SavedRun)
    assert (saved.id, saved.run_key, saved.status) == (
        waiting.id,
        the_saved_key(),
        JobStatus.SUCCEEDED,
    )
    assert dispatcher.calls == [f"submit {waiting.job_id}"]


def test_a_run_asked_to_stop_is_no_run_a_new_submission_waits_on(
    engine: Engine, workspace: LibraryTables
) -> None:
    executor, dispatcher = LookingUp(to_make()), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)
    first = runs.submit(asked(workspace))

    cancelled = runs.cancel(first.id)
    again = runs.submit(asked(workspace))

    assert cancelled.status == JobStatus.CANCELLED
    assert again.id != first.id
    assert again.status == JobStatus.QUEUED


def test_a_running_run_is_waited_on_until_it_is_asked_to_stop(
    engine: Engine, workspace: LibraryTables
) -> None:
    # Cancel, then Run again before the worker has stopped the first: the second submission must
    # not be the run that is about to end cancelled (the step's ponytail review).
    executor, dispatcher = LookingUp(to_make()), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)
    first = runs.submit(asked(workspace))
    JobTables(engine).start(first.job_id or "none", 4242, STARTED_AT, STARTED_AT)

    while_running = runs.submit(asked(workspace))
    stopping = runs.cancel(first.id)
    again = runs.submit(asked(workspace))

    assert while_running.id == first.id
    assert stopping.status == JobStatus.RUNNING
    assert (again.id != first.id, again.status) == (True, JobStatus.QUEUED)


def test_a_runs_status_is_its_jobs_until_it_is_saved(
    engine: Engine, workspace: LibraryTables
) -> None:
    executor, dispatcher = LookingUp(to_make()), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)
    job_id = runs.submit(asked(workspace)).job_id or "none"
    jobs = JobTables(engine)
    statuses = [runs.page(RunsAsked()).runs[0].status]

    jobs.start(job_id, 4242, STARTED_AT, STARTED_AT)
    statuses.append(runs.page(RunsAsked()).runs[0].status)
    jobs.requeue(job_id, 4242)
    statuses.append(runs.page(RunsAsked()).runs[0].status)

    assert statuses == [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.QUEUED]


def test_an_unknown_version_a_file_replaced_and_refused_code_are_refused(
    engine: Engine, workspace: LibraryTables
) -> None:
    refusal = RefusedCode(line=9, message="ValueError: no such column")
    executor, dispatcher = LookingUp(refusal), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)

    with pytest.raises(CodeRefusedError) as refused:
        runs.submit(asked(workspace))
    with pytest.raises(NoSuchStrategyError, match="Expected the id of a saved strategy version"):
        runs.submit(RunAsked("none", {}, *WINDOW, RunConfig()))
    file = resolve_paths(os.environ).strategies_dir / "breakout" / "v1.json"
    file.write_bytes(file.read_bytes().replace(b"rolling_max", b"rolling_min"))
    with pytest.raises(LibraryRefusedError):
        runs.submit(asked(workspace))

    assert (refused.value.line, str(refused.value)) == (9, "ValueError: no such column")
    assert dispatcher.calls == []
    assert (
        runs.records.page(strategy=None, versioned=None, status=None, cursor=None, limit=10).runs
        == ()
    )


def test_a_stress_asks_for_the_run_and_the_same_at_one_and_two_more_ticks(
    engine: Engine, workspace: LibraryTables
) -> None:
    # Step 5.6 (D-29): each variant is a run of its own, the ticks added to what the base applied.
    executor, dispatcher = LookingUp(to_make(None)), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)
    applied = to_make().settings.slippage_ticks

    stressed = runs.stressed(asked(workspace, lookback=24))

    lookups = [spec for spec in executor.specs if isinstance(spec, RunLookupSpec)]
    assert [spec.run.settings.slippage_ticks for spec in lookups] == [
        None,
        SlippageTicks(market=applied.market + 1, stop=applied.stop + 1),
        SlippageTicks(market=applied.market + 2, stop=applied.stop + 2),
    ]
    assert len({run.id for run in stressed.runs}) == 3
    assert len({run.job_id for run in stressed.runs}) == 3
    assert [each.split()[0] for each in dispatcher.calls] == ["submit"] * 3


def test_a_runs_job_is_queued_only_once_no_delete_holds_the_jobs_back(
    engine: Engine, workspace: LibraryTables
) -> None:
    # Step 5.18's reviews: the dispatcher's sweep gives a queued job to a worker by itself, so a
    # run's job is written queued only while no delete of stored data holds the jobs back.
    executor, dispatcher = LookingUp(to_make()), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)
    submitter = threading.Thread(target=runs.submit, args=(asked(workspace, lookback=24),))

    with runs.jobs.held_back() as under_way:
        submitter.start()
        submitter.join(timeout=0.5)
        waited = submitter.is_alive()
        queued_meanwhile = JobTables(engine).with_status(JobStatus.QUEUED)
    submitter.join(timeout=10)

    assert under_way == ()
    assert waited
    assert queued_meanwhile == ()
    assert len(JobTables(engine).with_status(JobStatus.QUEUED)) == 1


def run_again_through(runs: Runs, job_id: str) -> Job:
    """Run again of the job `job_id`, over the jobs of `runs`."""
    paths = resolve_paths(os.environ)
    catalog = MarketCatalog(Store(paths.data_dir), paths.reports_dir, paths.cache_dir, runs.jobs)
    return run_again(job_id, runs.jobs, runs, catalog)


def a_cancelled_submission(runs: Runs, workspace: LibraryTables) -> Job:
    """The job of a run asked for and cancelled while it was queued."""
    first = runs.submit(asked(workspace, lookback=24))
    assert isinstance(first, SubmittedRun)
    runs.cancel(first.id)
    return runs.jobs.by_id(first.job_id)


def test_run_again_of_a_cancelled_backtest_queues_a_run_of_the_same_request(
    engine: Engine, workspace: LibraryTables
) -> None:
    # Step 5.19: Run again is the undo of a Cancel, and the Runs list holds the run it makes.
    executor, dispatcher = LookingUp(to_make()), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)
    cancelled = a_cancelled_submission(runs, workspace)

    job = run_again_through(runs, cancelled.id)

    assert cancelled.status == JobStatus.CANCELLED
    assert (job.kind, job.status, job.payload) == (
        JobKind.BACKTEST,
        JobStatus.QUEUED,
        cancelled.payload,
    )
    assert job.id != cancelled.id
    assert dispatcher.calls[-1] == f"submit {job.id}"
    newest = runs.page(RunsAsked()).runs[0]
    assert (newest.job_id, newest.status) == (job.id, JobStatus.QUEUED)


def test_run_again_pressed_twice_queues_one_backtest_even_without_a_request_key(
    engine: Engine, workspace: LibraryTables
) -> None:
    # A strategy whose expressions call Python keys no request, so nothing else stops the second.
    executor, dispatcher = LookingUp(to_make(None)), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)
    cancelled = a_cancelled_submission(runs, workspace)

    first = run_again_through(runs, cancelled.id)
    second = run_again_through(runs, cancelled.id)

    assert second.id == first.id
    assert dispatcher.calls.count(f"submit {first.id}") == 1


def test_run_again_of_a_backtest_whose_run_was_saved_since_says_where_it_is(
    engine: Engine, workspace: LibraryTables
) -> None:
    executor, dispatcher = LookingUp(to_make()), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)
    cancelled = a_cancelled_submission(runs, workspace)
    executor.answer = SavedRunFound(
        run_key=the_saved_key(),
        request_key=REQUEST,
        parameters={"lookback": 24},
        settings=to_make().settings,
    )

    with pytest.raises(JobNotRunAgainError, match="open it on the Runs page"):
        run_again_through(runs, cancelled.id)


def test_run_again_of_a_version_the_library_no_longer_holds_is_refused(
    engine: Engine, workspace: LibraryTables
) -> None:
    executor, dispatcher = LookingUp(to_make()), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)
    payload = a_cancelled_submission(runs, workspace).payload
    replaced = {**payload, "run": {**payload["run"], "hash": "d" * 64}}
    other = JobTables(engine).add(JobKind.BACKTEST, replaced, 3, STARTED_AT)
    runs.jobs.cancel(other.id)

    with pytest.raises(JobNotRunAgainError, match="version 1 of the strategy breakout"):
        run_again_through(runs, other.id)


def test_run_again_of_inputs_this_version_cannot_read_is_refused(
    engine: Engine, workspace: LibraryTables
) -> None:
    executor, dispatcher = LookingUp(to_make()), RecordingDispatcher()
    runs = runs_over(engine, workspace, executor, dispatcher)
    other = JobTables(engine).add(JobKind.BACKTEST, {"kind": "backtest"}, 3, STARTED_AT)
    runs.jobs.cancel(other.id)

    with pytest.raises(JobNotRunAgainError, match="run it from its strategy's page"):
        run_again_through(runs, other.id)
