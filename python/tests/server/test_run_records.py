"""The runs' records (step 5.3, `fefat_app.database.run_records`, ADR-0020): a submission makes a run
and its queued `backtest` job in one transaction, and a second submission of one request is the
first while its job is active and not asked to stop; a saved folder's record gives a row its run
key and its columns, the row of the job that made it, or of the submission waiting on its request,
or a new row; one row holds a run key, whichever jobs made the run; and a run's status is its
job's until its folder is saved, `succeeded` after."""

import os
import shutil
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine

from fefat.backtest import AppliedRunConfig, Run, saved_runs_in
from fefat.config import resolve_paths
from fefat_app.database.job_records import JobTables
from fefat_app.database.library_index import LibraryTables
from fefat_app.database.run_records import RunTables
from fefat_app.job_models import JobKind, JobStatus
from fefat_app.runs import NewRun, RunOrigin
from local_server import STARTED_AT

WINDOW = (date(2026, 3, 5), date(2026, 3, 9))
REQUEST = "c" * 64


@pytest.fixture
def records(breakout_workspace: Path, engine: Engine) -> RunTables:
    """The runs' records over the test's database, its workspace a copy of the one made, its
    library indexed."""
    paths = resolve_paths(os.environ)
    shutil.copytree(breakout_workspace, paths.workspace_dir)
    LibraryTables(engine, paths).refresh()
    return RunTables(engine, paths)


def the_run() -> Run:
    (run,) = saved_runs_in(resolve_paths(os.environ).runs_dir)
    return run


def the_version_id(engine: Engine) -> str:
    paths = resolve_paths(os.environ)
    (strategy,) = LibraryTables(engine, paths).strategies()
    return strategy.versions[0].id


def a_submission(engine: Engine, request_key: str | None = REQUEST) -> NewRun:
    """A submission of version 1 of `breakout` with its defaults, the settings its run applied."""
    return NewRun(
        strategy_version_id=the_version_id(engine),
        payload={"spec": "the backtest's"},
        parameters={"lookback": 12, "stop_atr": 1.5},
        start=WINDOW[0],
        end=WINDOW[1],
        settings=the_run().config,
        request_key=request_key,
    )


def test_a_submission_makes_a_run_and_its_queued_job(records: RunTables, engine: Engine) -> None:
    submitted = records.submitted(a_submission(engine), 3, STARTED_AT)

    job = JobTables(engine).by_id(submitted.queued_job_id or "none")
    run = submitted.run
    assert job is not None
    assert (job.kind, job.status, job.payload, job.max_attempts) == (
        JobKind.BACKTEST,
        JobStatus.QUEUED,
        {"spec": "the backtest's"},
        3,
    )
    assert (run.job_id, run.status, run.progress, run.run_key) == (
        job.id,
        JobStatus.QUEUED,
        0,
        None,
    )
    assert (run.origin, run.created_at, run.start, run.end) == (
        RunOrigin.MANUAL,
        STARTED_AT,
        *WINDOW,
    )
    assert run.strategy is not None
    assert (run.strategy.name, run.strategy.version) == ("breakout", 1)
    assert records.newest(10) == (run,)


def test_a_second_submission_of_one_request_is_the_first_while_its_job_is_active(
    records: RunTables, engine: Engine
) -> None:
    first = records.submitted(a_submission(engine), 3, STARTED_AT)
    second = records.submitted(a_submission(engine), 3, STARTED_AT)
    jobs = JobTables(engine)
    jobs.cancel_queued(first.run.job_id or "none", STARTED_AT)
    third = records.submitted(a_submission(engine), 3, STARTED_AT)

    assert (second.run.id, second.queued_job_id) == (first.run.id, None)
    assert third.run.id != first.run.id
    assert third.queued_job_id is not None
    without_requests = [records.submitted(a_submission(engine, None), 3, STARTED_AT)]
    without_requests.append(records.submitted(a_submission(engine, None), 3, STARTED_AT))
    assert len({each.run.id for each in without_requests}) == 2


def test_a_saved_run_takes_its_key_and_the_columns_of_its_record(
    records: RunTables, engine: Engine
) -> None:
    submitted = records.submitted(a_submission(engine), 3, STARTED_AT)
    run = the_run()

    saved = records.saved(run.hash, job_id=submitted.queued_job_id)
    read = records.by_id(saved.id)

    assert (saved.id, saved.run_key, saved.status, saved.progress) == (
        submitted.run.id,
        run.hash,
        JobStatus.SUCCEEDED,
        100,
    )
    assert (saved.start, saved.end) == (run.record.window.start, run.record.window.end)
    assert saved.settings == run.config
    assert saved.parameters == {"lookback": 12, "stop_atr": 1.5}
    assert read is not None
    assert read.metrics == run.metrics
    assert read.fidelity_eras == run.record.fidelity_eras
    assert read.warnings == run.record.warnings
    assert records.saved(run.hash) == saved


def test_a_run_found_saved_before_its_job_indexed_it_is_that_jobs_row(
    records: RunTables, engine: Engine
) -> None:
    # A POST whose lookup finds the run that a waiting submission's job wrote but has not yet
    # indexed saves that submission's row, which the job then finds holding its key.
    submitted = records.submitted(a_submission(engine), 3, STARTED_AT)
    run = the_run()

    found = records.saved(run.hash, request_key=REQUEST)
    by_the_job = records.saved(run.hash, job_id=submitted.queued_job_id)

    assert found.id == by_the_job.id == submitted.run.id
    assert len(records.newest(10)) == 1


def test_two_jobs_whose_runs_share_a_key_leave_one_row(records: RunTables, engine: Engine) -> None:
    # A strategy whose expressions call Python keys no request, so two submissions of it each
    # queue a job; the second job's run is the first's, whose row it names.
    first = records.submitted(a_submission(engine, None), 3, STARTED_AT)
    second = records.submitted(a_submission(engine, None), 3, STARTED_AT)
    run = the_run()

    kept = records.saved(run.hash, job_id=first.queued_job_id)
    again = records.saved(run.hash, job_id=second.queued_job_id)

    assert again.id == kept.id == first.run.id
    assert records.by_id(second.run.id) is None
    assert [each.id for each in records.newest(10)] == [kept.id]


def test_a_saved_run_no_submission_made_gets_a_row_of_its_own(
    records: RunTables, engine: Engine
) -> None:
    run = the_run()

    saved = records.saved(run.hash)

    assert (saved.job_id, saved.created_at) == (None, run.saved_at)
    assert saved.strategy is not None
    assert saved.strategy.version_id == the_version_id(engine)


def test_a_run_key_that_names_no_run_of_its_own_folder_is_refused(records: RunTables) -> None:
    run = the_run()
    shutil.copytree(run.folder, run.folder.with_name("e" * 64))

    with pytest.raises(ValueError, match="Expected a run key, 64 hexadecimal digits"):
        records.saved("../" + run.hash)
    with pytest.raises(ValueError, match=f"Expected the run of key {'e' * 64}"):
        records.saved("e" * 64)


def test_a_saved_runs_settings_read_back_whole(records: RunTables) -> None:
    saved = records.saved(the_run().hash)

    assert isinstance(saved.settings, AppliedRunConfig)
    assert saved.settings.provider == "synthetic"
