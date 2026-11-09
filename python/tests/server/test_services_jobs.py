"""The jobs' service of step 4.4 (`01-architecture.md` section 6) over the jobs' records and a
dispatcher that runs nothing: a demo job is queued and given to the dispatcher; a queued job is
cancelled at once, a running one asked to stop, an ended one left as it is; and an unknown id is
refused (Done means 1: cancellation)."""

from datetime import timedelta

import pytest

from fefat_app.database.job_records import JobTables
from fefat_app.ports import JobKind, JobStatus
from fefat_app.services.jobs import Jobs, NoSuchJobError
from local_server import STARTED_AT, RecordingDispatcher, SettableClock

WORKER = 4242


@pytest.fixture
def dispatcher() -> RecordingDispatcher:
    return RecordingDispatcher()


@pytest.fixture
def jobs(job_records: JobTables, dispatcher: RecordingDispatcher, clock: SettableClock) -> Jobs:
    return Jobs(job_records, dispatcher, clock)


def test_a_demo_job_is_queued_and_given_to_the_dispatcher(
    jobs: Jobs, dispatcher: RecordingDispatcher
) -> None:
    job = jobs.start_demo(60)

    assert (job.kind, job.payload, job.status) == (JobKind.DEMO, {"seconds": 60}, JobStatus.QUEUED)
    assert (job.max_attempts, job.created_at) == (3, STARTED_AT)
    assert dispatcher.calls == [f"submit {job.id}"]
    assert jobs.recent() == (job,)


def test_a_queued_job_is_cancelled_at_once(jobs: Jobs) -> None:
    job = jobs.start_demo(60)

    cancelled = jobs.cancel(job.id)

    assert (cancelled.status, cancelled.finished_at) == (JobStatus.CANCELLED, STARTED_AT)


def test_a_running_job_is_asked_to_stop(
    jobs: Jobs, job_records: JobTables, clock: SettableClock
) -> None:
    job = jobs.start_demo(60)
    job_records.start(job.id, WORKER, STARTED_AT + timedelta(seconds=15), STARTED_AT)
    clock.advance(timedelta(seconds=5))

    asked = jobs.cancel(job.id)
    again = jobs.cancel(job.id)

    assert (asked.status, asked.cancel_requested_at) == (JobStatus.RUNNING, clock.now)
    assert again == asked


def test_an_ended_job_is_left_as_it_is(jobs: Jobs, job_records: JobTables) -> None:
    job = jobs.start_demo(1)
    job_records.start(job.id, WORKER, STARTED_AT + timedelta(seconds=15), STARTED_AT)
    ended = job_records.finish(job.id, WORKER, JobStatus.SUCCEEDED, STARTED_AT, result={})

    assert jobs.cancel(job.id) == ended


def test_an_unknown_job_is_refused(jobs: Jobs) -> None:
    with pytest.raises(NoSuchJobError, match="Expected the id of a job, got 'nope'"):
        jobs.by_id("nope")
    with pytest.raises(NoSuchJobError):
        jobs.cancel("nope")
