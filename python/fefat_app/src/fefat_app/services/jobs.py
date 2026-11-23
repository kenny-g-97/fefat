"""The jobs (step 4.4, `01-architecture.md` section 6): a job of each kind starts here, the demo
job and, through each area's service, the others, such as the catalog sync (step 5.1); the list of
jobs and each job read from here, a job is cancelled here, and a stream's events are read from
here for the server's streams. A queued job is cancelled at once; a running one is asked to stop,
which its worker reads at its next report, or after which the reaper ends it, unless it has come
past the point where it can stop, as an import that writes (step 5.12)."""

import threading
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fefat_app.imports import WRITING_PERCENT
from fefat_app.job_models import ACTIVE, Job, JobKind, JobStatus, StreamEvent
from fefat_app.ports import Clock, Dispatcher, JobRecords

MAX_ATTEMPTS = 3
"""How many times a job runs before a worker that stops answering fails it."""
RECENT_JOBS = 100
"""How many of the newest jobs the list holds, beside the running jobs older than them."""
CANCEL_TRIES = 3
"""How many times a cancel reads its job again after the job changed under it, as when the
reaper queues it again; a race that repeats faster than a read takes is no race."""
STOPPABLE_BELOW: Mapping[JobKind, float] = {JobKind.IMPORT: WRITING_PERCENT}
"""The progress from which a running job of a kind no longer stops: an import's once it writes,
since an import stopped then is finished only by running it again (ADR-0021). The request to
stop is refused in the same write that would make it, so that a job that reached the point in
between is never asked, and its worker never ended by the reaper."""


class NoSuchJobError(ValueError):
    """A job's id that no job has."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"Expected the id of a job, got {job_id!r}.")


class JobPastStoppingError(ValueError):
    """A running job asked to stop past the point where it can (`STOPPABLE_BELOW`)."""

    def __init__(self, job: Job) -> None:
        super().__init__(
            f"Expected a job that can still stop, got the import {job.id}, which writes its "
            "partitions now: an import runs to its end once it writes, since one stopped then "
            "is finished only by importing its file again."
        )


@dataclass(frozen=True)
class Jobs:
    """Starts, lists, reads, and cancels jobs, over their records and the dispatcher; `starting`
    is held while a job is given to the dispatcher, and by a delete of stored data for as long as
    it runs (`held_back`, step 5.18)."""

    records: JobRecords
    dispatcher: Dispatcher
    clock: Clock
    starting: threading.Lock = field(default_factory=threading.Lock, compare=False, repr=False)

    def start(self, kind: JobKind, payload: Mapping[str, Any]) -> Job:
        """Queue a job of `kind` with `payload`, and give it to the dispatcher, once no delete
        holds the jobs back."""
        with self.starting:
            job = self.records.add(kind, payload, MAX_ATTEMPTS, self.clock())
            self.dispatcher.submit(job.id)
        return job

    def submit(self, job_id: str) -> None:
        """Give the dispatcher the queued job `job_id`, which another area's records queued, as
        the runs' records queue a run's job with its row (step 5.3), once no delete holds the
        jobs back."""
        with self.starting:
            self.dispatcher.submit(job_id)

    def queued_by[Queued](self, queue: Callable[[], Queued]) -> Queued:
        """What `queue` gives, which writes a job queued in another area's records, as the runs'
        records queue a run's job with its row (step 5.3), once no delete holds the jobs back:
        the dispatcher's sweep gives a queued job to a worker by itself, so that a delete sees
        such a job queued, and is refused, or holds it back until it ends (step 5.18)."""
        with self.starting:
            return queue()

    @contextmanager
    def held_back(self) -> Generator[tuple[Job, ...]]:
        """Hold every job back from being given to the dispatcher until the block ends, as a
        delete of stored data does while it removes what a job could read or write (step 5.18),
        and give the jobs already queued or running."""
        with self.starting:
            yield self.under_way()

    def start_demo(self, seconds: int) -> Job:
        """Queue a demo job that counts `seconds`, and give it to the dispatcher."""
        return self.start(JobKind.DEMO, {"seconds": seconds})

    def under_way(self) -> tuple[Job, ...]:
        """Every job that is queued, then every one that runs, each oldest first."""
        return tuple(job for status in ACTIVE for job in self.records.with_status(status))

    def active(self, kind: JobKind) -> tuple[Job, ...]:
        """The jobs of `kind` that are queued, then those that run, each oldest first."""
        return tuple(job for job in self.under_way() if job.kind == kind)

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
        that has ended, or that was asked before, is given as it is, and one past the point
        where it can stop is refused (`JobPastStoppingError`). A job the reaper queued again, or
        a worker started or moved on, since it was read is read again, `CANCEL_TRIES` times at
        most, after which it is given as it is."""
        now = self.clock()
        job = self.by_id(job_id)
        for _ in range(CANCEL_TRIES):
            if job.status not in ACTIVE or job.cancel_requested_at is not None:
                return job
            changed = self._cancelled(job, now)
            if changed is not None:
                return changed
            job = self.by_id(job_id)
        return job

    def _cancelled(self, job: Job, now: datetime) -> Job | None:
        if job.status == JobStatus.QUEUED:
            return self.records.cancel_queued(job.id, now)
        stoppable_below = STOPPABLE_BELOW.get(job.kind)
        if stoppable_below is not None and job.progress >= stoppable_below:
            raise JobPastStoppingError(job)
        return self.records.request_cancel(job.id, now, stoppable_below=stoppable_below)

    def events_after(self, stream_id: str, after_id: int, limit: int) -> tuple[StreamEvent, ...]:
        """At most `limit` events of the stream `stream_id` after the event `after_id`."""
        return self.records.events_after(stream_id, after_id, limit)

    def job_events_after(self, after_id: int, limit: int) -> tuple[StreamEvent, ...]:
        """At most `limit` events of every job's stream after the event `after_id`."""
        return self.records.job_events_after(after_id, limit)

    def newest_event_id(self) -> int:
        """The id of the newest event kept, where a stream opened anew starts."""
        return self.records.newest_event_id()

    def has_ended(self, job_id: str) -> bool:
        """Whether the job `job_id` reached one of its ends; `NoSuchJobError` where there is
        none. Its last status event is kept in the same write, so that a read of the events
        made after this says true holds that event."""
        return self.by_id(job_id).status not in ACTIVE
