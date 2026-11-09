"""The jobs (step 4.4, `01-architecture.md` section 6): the demo job starts here, the list of
jobs and each job read from here, a job is cancelled here, and a stream's events are read from
here for the server's streams. A queued job is cancelled at once; a running one is asked to stop,
which its worker reads at its next report, or after which the reaper ends it."""

from dataclasses import dataclass

from fefat_app.ports import Clock, Dispatcher, Job, JobKind, JobRecords, StreamEvent

MAX_ATTEMPTS = 3
"""How many times a job runs before a worker that stops answering fails it."""
RECENT_JOBS = 100
"""How many of the newest jobs the list holds."""


class NoSuchJobError(ValueError):
    """A job's id that no job has."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Expected the id of a job, got {job_id!r}.")


@dataclass(frozen=True)
class Jobs:
    """Starts, lists, reads, and cancels jobs, over their records and the dispatcher."""

    records: JobRecords
    dispatcher: Dispatcher
    clock: Clock

    def start_demo(self, seconds: int) -> Job:
        """Queue a demo job that counts `seconds`, and give it to the dispatcher."""
        job = self.records.add(JobKind.DEMO, {"seconds": seconds}, MAX_ATTEMPTS, self.clock())
        self.dispatcher.submit(job.id)
        return job

    def recent(self) -> tuple[Job, ...]:
        """The newest jobs, newest first."""
        return self.records.recent(RECENT_JOBS)

    def by_id(self, job_id: str) -> Job:
        """The job `job_id`; `NoSuchJobError` where there is none."""
        job = self.records.by_id(job_id)
        if job is None:
            raise NoSuchJobError(job_id)
        return job

    def cancel(self, job_id: str) -> Job:
        """Cancel the job `job_id` at once if it is queued, or ask it to stop if it runs; a job
        that has ended, or that was asked before, is given as it is."""
        now = self.clock()
        cancelled = self.records.cancel_queued(job_id, now)
        if cancelled is not None:
            return cancelled
        asked = self.records.request_cancel(job_id, now)
        if asked is not None:
            return asked
        return self.by_id(job_id)

    def events_after(self, stream_id: str, after_id: int, limit: int) -> tuple[StreamEvent, ...]:
        """At most `limit` events of the stream `stream_id` after the event `after_id`."""
        return self.records.events_after(stream_id, after_id, limit)
