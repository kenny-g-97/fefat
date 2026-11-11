"""How a job's work reports how far it has come (step 4.4, `01-architecture.md` section 6): each
report, made between two chunks of the work, writes the job's progress and a `progress` event,
and stops the work where the job was asked to stop, or where its worker no longer holds it; and,
for work that reports seldom, as the trader's code run by the executor does, a check that stops it
alike without a report (step 4.5)."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import OperationalError

from fefat_app.job_models import Job, JobStatus
from fefat_app.ports import JobRecords


class JobCancelledError(Exception):
    """The work stops here: its job was asked to stop, or its worker no longer holds it."""


@dataclass(frozen=True)
class JobProgress:
    """The reports of the job `job_id`, which the worker `worker_pid` holds."""

    records: JobRecords
    job_id: str
    worker_pid: int

    def advance(self, percent: float, message: str, **details: Any) -> None:
        """Report `percent` of the work done, with `message` and any `details` of its kind;
        `JobCancelledError` where the work must stop. A report that a writer holding the database
        past its busy timeout refused is skipped, the next one reporting again and checking for
        a request to stop."""
        if not 0 <= percent <= 100:
            raise ValueError(
                f"Expected a percent from 0 to 100 for the job {self.job_id}, got {percent}."
            )
        try:
            job = self.records.advance(self.job_id, self.worker_pid, percent, message, details)
        except OperationalError:
            return
        self._stop_unless_held(job)

    def check(self) -> None:
        """`JobCancelledError` where the work must stop, as at a report, without writing one; a
        read the busy database refused is skipped, the next check reading again."""
        try:
            job = self.records.by_id(self.job_id)
        except OperationalError:
            return
        self._stop_unless_held(self._held(job))

    def _held(self, job: Job | None) -> Job | None:
        """`job` where this worker runs it, else None."""
        if job is None or job.status != JobStatus.RUNNING or job.worker_pid != self.worker_pid:
            return None
        return job

    def _stop_unless_held(self, job: Job | None) -> None:
        """Stop the work where the worker no longer holds `job`, None then, or where it was asked
        to stop."""
        if job is None:
            raise JobCancelledError(
                f"The job {self.job_id} is no longer held by the worker {self.worker_pid}."
            )
        if job.cancel_requested_at is not None:
            raise JobCancelledError(f"The job {self.job_id} was asked to stop.")
