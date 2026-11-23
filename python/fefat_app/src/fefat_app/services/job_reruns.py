"""Run again (step 5.19, D-115): a job that failed, was cancelled, or timed out, run once more from
the inputs its own row holds, which is the undo of a Cancel. Each kind goes through what starts
it, so that its rules hold: a backtest through its run, which the Runs list then shows, and a
quality check through the one sync of a product at a time. Work already queued or running under
the same inputs is that job, so that a second press or a second tab queues nothing."""

from pydantic import ValidationError

from fefat_app.execution import BacktestSpec
from fefat_app.job_models import ACTIVE, Job, JobKind, JobStatus
from fefat_app.library import LibraryRefusedError
from fefat_app.runs import SavedRun
from fefat_app.services.catalog import MarketCatalog, NothingToSyncError
from fefat_app.services.code_runs import CodeRefusedError
from fefat_app.services.jobs import Jobs
from fefat_app.services.runs import Runs
from fefat_app.services.strategies import NoSuchStrategyError


class JobNotRunAgainError(ValueError):
    """A job Run again refuses: one under way or succeeded, or whose inputs no longer run."""


def run_again(job_id: str, jobs: Jobs, runs: Runs, catalog: MarketCatalog) -> Job:
    """The job that runs the inputs of the job `job_id` again (module docstring);
    `NoSuchJobError` for an unknown id and `JobNotRunAgainError` for a job that does not."""
    job = jobs.by_id(job_id)
    if job.status in (*ACTIVE, JobStatus.SUCCEEDED):
        raise JobNotRunAgainError(
            "Expected a job that failed, was cancelled, or timed out, got the job "
            f"{job.id}, which is {job.status.value}."
        )
    try:
        if job.kind == JobKind.BACKTEST:
            return _backtest_again(job, jobs, runs)
        if job.kind == JobKind.CATALOG_SYNC:
            return catalog.start_sync(job.payload["root"])
    except (
        CodeRefusedError,
        LibraryRefusedError,
        NoSuchStrategyError,
        NothingToSyncError,
    ) as refused:
        raise JobNotRunAgainError(str(refused)) from refused
    return jobs.start_unless_under_way(job.kind, job.payload)


def _backtest_again(job: Job, jobs: Jobs, runs: Runs) -> Job:
    """The job of `job`'s backtest asked for again: the same one under way, which a strategy that
    keys no request has nothing else to find it by, or else the job of its new run."""
    under_way = jobs.under_way_with(job.kind, job.payload)
    if under_way is not None:
        return under_way
    try:
        spec = BacktestSpec.model_validate(job.payload)
    except ValidationError as unread:
        raise JobNotRunAgainError(
            f"Expected the inputs of a backtest, got those of the job {job.id} in a form this "
            "version of FEAT cannot read: run it from its strategy's page."
        ) from unread
    run = runs.submit_again(spec.run)
    if isinstance(run, SavedRun):
        raise JobNotRunAgainError(
            f"Expected a run still to make, got the run of the job {job.id} saved since: open "
            "it on the Runs page."
        )
    return jobs.by_id(run.job_id)
