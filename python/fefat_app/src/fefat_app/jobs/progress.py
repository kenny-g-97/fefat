"""How a job's work reports how far it has come (step 4.4, `01-architecture.md` section 6): each
report, made between two chunks of the work, writes the job's progress and a `progress` event,
and stops the work where the job was asked to stop, or where its worker no longer holds it."""

from dataclasses import dataclass
from typing import Any

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
        `JobCancelledError` where the work must stop."""
        if not 0 <= percent <= 100:
            raise ValueError(f"Expected a percent from 0 to 100, got {percent}.")
        job = self.records.advance(self.job_id, self.worker_pid, percent, message, details)
        if job is None:
            raise JobCancelledError(
                f"The job {self.job_id} is no longer held by the worker {self.worker_pid}."
            )
        if job.cancel_requested_at is not None:
            raise JobCancelledError(f"The job {self.job_id} was asked to stop.")
