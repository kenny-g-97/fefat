"""Run again (step 5.19, D-115): a job that failed, was cancelled, or timed out, run once more from
the inputs its own row holds, which is the undo of a Cancel. Each kind goes through what starts
it, so that its rules hold: a backtest through its run, which the Runs list then shows, a quality
check through the one sync of a product at a time, and an import through the checks of its files.
Work already queued or running under the same inputs is that job, so that a second press or a
second tab queues nothing. A refusal is said to the trader, in the jobs drawer."""

import threading

from pydantic import ValidationError

from fefat_app.execution import BacktestSpec
from fefat_app.imports import (
    REPORT_FAILED,
    NoSuchUploadError,
    PathRefusedError,
    ProfileRefusedError,
)
from fefat_app.job_models import ACTIVE, Job, JobKind, JobStatus
from fefat_app.library import LibraryRefusedError
from fefat_app.runs import SavedRun
from fefat_app.services.catalog import MarketCatalog, NothingToSyncError
from fefat_app.services.code_runs import CodeRefusedError
from fefat_app.services.imports import Imports
from fefat_app.services.jobs import Jobs
from fefat_app.services.runs import Runs
from fefat_app.services.strategies import NoSuchStrategyError

_BACKTEST_AGAIN = threading.Lock()
"""Held across a backtest's lookup, which takes seconds and so cannot hold the lock that starts
every job, so that a second press finds the first one's job."""


class JobNotRunAgainError(ValueError):
    """A job Run again refuses: one under way or succeeded, or whose inputs no longer run."""


def run_again(job_id: str, jobs: Jobs, runs: Runs, catalog: MarketCatalog, imports: Imports) -> Job:
    """The job that runs the inputs of the job `job_id` again (module docstring);
    `NoSuchJobError` for an unknown id and `JobNotRunAgainError` for a job that does not."""
    job = jobs.by_id(job_id)
    if job.status in (*ACTIVE, JobStatus.SUCCEEDED):
        raise JobNotRunAgainError(
            "Only a job that failed, was cancelled, or timed out runs again; this one's status "
            f"is {job.status.value}."
        )
    try:
        if job.kind == JobKind.BACKTEST:
            with _BACKTEST_AGAIN:
                return _backtest_again(job, jobs, runs)
        if job.kind == JobKind.CATALOG_SYNC:
            return catalog.start_sync(job.payload["root"])
        if job.kind == JobKind.IMPORT:
            return _import_again(job, imports)
    except ValidationError as unread:
        raise JobNotRunAgainError(
            "This job's inputs were saved by another version of FEAT. Start it again from its page."
        ) from unread
    except NoSuchUploadError as gone:
        raise JobNotRunAgainError(
            "The file this import read is no longer kept. Import it again from the Data page."
        ) from gone
    except PathRefusedError as moved:
        raise JobNotRunAgainError(
            "This import's file is no longer where it was, or its folder is no longer an "
            "import root. Import it again from the Data page."
        ) from moved
    except NothingToSyncError as gone:
        raise JobNotRunAgainError(
            "FEAT no longer holds this data, so there is nothing to check. Import it again "
            "from the Data page."
        ) from gone
    except (
        CodeRefusedError,
        LibraryRefusedError,
        NoSuchStrategyError,
        ProfileRefusedError,
    ) as refused:
        raise JobNotRunAgainError(str(refused)) from refused
    return jobs.start_unless_under_way(job.kind, job.payload)


def _backtest_again(job: Job, jobs: Jobs, runs: Runs) -> Job:
    """The job of `job`'s backtest asked for again: the same one under way, which a strategy that
    keys no request has nothing else to find it by, or else the job of its new run."""
    under_way = jobs.under_way_with(job.kind, job.payload)
    if under_way is not None:
        return under_way
    run = runs.submit_again(BacktestSpec.model_validate(job.payload).run)
    if isinstance(run, SavedRun):
        raise JobNotRunAgainError("This backtest has been saved since. Open it on the Runs page.")
    return jobs.by_id(run.job_id)


def _import_again(job: Job, imports: Imports) -> Job:
    """The import of `job` queued again, unless it wrote its data and only its report failed:
    importing the file again would find it imported, end green, and write no report.
    shortcut: read from the words of its error, until a job keeps a typed reason."""
    if job.error is not None and REPORT_FAILED in job.error:
        raise JobNotRunAgainError(
            "This import wrote its data and only its quality report failed. Press Check quality "
            "on its dataset's page, and import again any file it left out."
        )
    return imports.start_again(job)
