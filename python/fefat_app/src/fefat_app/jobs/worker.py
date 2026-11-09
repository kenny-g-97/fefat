"""A job's run in a worker process of the pool (step 4.4, `01-architecture.md` section 6):
`run_job` starts the queued job in this process, renews its lease from a thread of its own while
the work runs, so that the reaper knows the worker answers, and ends the job as the work ends.

The worker opens the database itself, in WAL mode with the busy timeout of
`fefat_app.database.schema`, since it runs in another process from the server's, and it reads the
system's clock, the server's `Clock` being a seam of the server's own process."""

import os
import threading
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.exc import OperationalError

from fefat_app.database.job_records import JobTables
from fefat_app.database.schema import opened_database
from fefat_app.jobs.demo import run_demo
from fefat_app.jobs.progress import JobCancelledError, JobProgress
from fefat_app.ports import Job, JobEnd, JobKind, JobRecords, JobStatus

type JobWork = Callable[[Mapping[str, Any], JobProgress], dict[str, Any]]
"""A kind's work: it takes the job's payload and reports through its progress; its result."""

WORK_BY_KIND: Mapping[JobKind, JobWork] = {JobKind.DEMO: run_demo}
"""The work of each kind a worker runs; the steps of later phases add theirs."""
END_TRIES = 12
"""How many times a worker writes its job's end while a writer holds the database past its busy
timeout of five seconds: a minute, while the heartbeat keeps the lease."""


@dataclass(frozen=True)
class JobTimings:
    """How long a worker's lease runs and how often the worker renews it, how often the reaper
    looks for workers that stopped answering, and how long a job asked to stop may run on before
    the reaper ends its worker; the tests shorten them."""

    lease_seconds: float = 15.0
    heartbeat_seconds: float = 3.0
    reaper_period_seconds: float = 3.0
    cancel_grace_seconds: float = 10.0


def run_job(job_id: str, database_file: Path, timings: JobTimings) -> None:
    """Run the queued job `job_id` of the database `database_file` in this process; a job that
    another worker took, or that was cancelled while queued, is left as it is."""
    with opened_database(database_file) as engine:
        records = JobTables(engine)
        worker_pid = os.getpid()
        now = datetime.now(UTC)
        job = records.start(job_id, worker_pid, now + timedelta(seconds=timings.lease_seconds), now)
        if job is None:
            return
        with _lease_kept(records, job_id, worker_pid, timings):
            _run(records, job, worker_pid)


def _run(records: JobRecords, job: Job, worker_pid: int) -> None:
    """Run `job`'s work and end the job as the work ended, trying the end again while a writer
    holds the database past its busy timeout, so that a job whose work ended never stays
    running until its lease runs out."""
    end, result, error = _outcome(records, job, worker_pid)
    for attempt in range(1, END_TRIES + 1):
        try:
            records.finish(job.id, worker_pid, end, datetime.now(UTC), result=result, error=error)
            return
        except OperationalError:
            if attempt == END_TRIES:
                raise


def _outcome(
    records: JobRecords, job: Job, worker_pid: int
) -> tuple[JobEnd, dict[str, Any] | None, str | None]:
    """How `job`'s work ended: its end, with its result where it succeeded, or its reason where
    it failed."""
    try:
        work = _work_of(job.kind)
        result = work(job.payload, JobProgress(records, job.id, worker_pid))
    except JobCancelledError:
        return JobStatus.CANCELLED, None, None
    except Exception as failure:
        return JobStatus.FAILED, None, f"{type(failure).__name__}: {failure}"
    return JobStatus.SUCCEEDED, result, None


def _work_of(kind: JobKind) -> JobWork:
    work = WORK_BY_KIND.get(kind)
    if work is None:
        runs = ", ".join(WORK_BY_KIND)
        raise ValueError(f"Expected a job kind the worker runs ({runs}), got {kind.value}.")
    return work


@contextmanager
def _lease_kept(
    records: JobRecords, job_id: str, worker_pid: int, timings: JobTimings
) -> Generator[None]:
    """Renew the lease of the job `job_id` every `heartbeat_seconds` while the block runs."""
    stopped = threading.Event()
    heartbeat = threading.Thread(
        target=_renew_until,
        args=(records, job_id, worker_pid, timings, stopped),
        name=f"lease of job {job_id}",
        daemon=True,
    )
    heartbeat.start()
    try:
        yield
    finally:
        stopped.set()
        heartbeat.join()


def _renew_until(
    records: JobRecords, job_id: str, worker_pid: int, timings: JobTimings, stopped: threading.Event
) -> None:
    """Renew the lease until `stopped` is set, or until the worker no longer holds the job; a
    renewal that a writer holding the database past its busy timeout refused is tried again at
    the next beat, several of which fit in a lease, so that the reaper never ends a worker that
    answers."""
    while not stopped.wait(timings.heartbeat_seconds):
        lease_until = datetime.now(UTC) + timedelta(seconds=timings.lease_seconds)
        try:
            held = records.renew_lease(job_id, worker_pid, lease_until)
        except OperationalError:
            continue
        if not held:
            return
