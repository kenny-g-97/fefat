"""The jobs (step 4.4, `01-architecture.md` section 6): the demo job starts here, the list of
jobs and each job read from here, a job is cancelled here, and a stream's events are read from
here for the server's streams. A queued job is cancelled at once; a running one is asked to stop,
which its worker reads at its next report, or after which the reaper ends it."""

from dataclasses import dataclass

from fefat_app.ports import Clock, Dispatcher, Job, JobKind, JobRecords, JobStatus, StreamEvent

MAX_ATTEMPTS = 3
"""How many times a job runs before a worker that stops answering fails it."""
RECENT_JOBS = 100
"""How many of the newest jobs the list holds, beside the running jobs older than them."""
ACTIVE = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})
"""The statuses of a job that has not ended."""
CANCEL_TRIES = 3
"""How many times a cancel reads its job again after the job changed under it, as when the
reaper queues it again; a race that repeats faster than a read takes is no race."""


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
        """The newest jobs, newest first, then the running jobs older than them, which a queue
        of newer jobs would otherwise hide with their progress and their Cancel."""
        newest = self.records.recent(RECENT_JOBS)
        listed = {job.id for job in newest}
        running = self.records.with_status(JobStatus.RUNNING)
        return newest + tuple(job for job in running if job.id not in listed)

    def by_id(self, job_id: str) -> Job:
        """The job `job_id`; `NoSuchJobError` where there is none."""
        job = self.records.by_id(job_id)
        if job is None:
            raise NoSuchJobError(job_id)
        return job

    def cancel(self, job_id: str) -> Job:
        """Cancel the job `job_id` at once if it is queued, or ask it to stop if it runs; a job
        that has ended, or that was asked before, is given as it is. A job the reaper queued
        again, or a worker started, since it was read is read again, `CANCEL_TRIES` times at
        most, after which it is given as it is."""
        now = self.clock()
        job = self.by_id(job_id)
        for _ in range(CANCEL_TRIES):
            if job.status not in ACTIVE or job.cancel_requested_at is not None:
                return job
            if job.status == JobStatus.QUEUED:
                changed = self.records.cancel_queued(job_id, now)
            else:
                changed = self.records.request_cancel(job_id, now)
            if changed is not None:
                return changed
            job = self.by_id(job_id)
        return job

    def events_after(self, stream_id: str, after_id: int, limit: int) -> tuple[StreamEvent, ...]:
        """At most `limit` events of the stream `stream_id` after the event `after_id`."""
        return self.records.events_after(stream_id, after_id, limit)
