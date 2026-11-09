"""The jobs' records of step 4.4 (`01-architecture.md` section 6, D-90): the state machine as
compare-and-set updates, each status change with its event in the job's stream, a worker's own
changes refused to any other worker, and the events read back in order after the last one seen
(Done means 1: the state transitions)."""

from datetime import timedelta

import pytest

from fefat_app.database.job_records import JobTables
from fefat_app.ports import Job, JobKind, JobStatus, job_stream
from local_server import STARTED_AT

WORKER = 4242
OTHER_WORKER = 4343
LEASE_UNTIL = STARTED_AT + timedelta(seconds=15)


def a_demo(job_records: JobTables, seconds: int = 3) -> Job:
    return job_records.add(JobKind.DEMO, {"seconds": seconds}, 3, STARTED_AT)


def started(job_records: JobTables, job: Job, worker: int = WORKER) -> Job:
    running = job_records.start(job.id, worker, LEASE_UNTIL, STARTED_AT)
    assert running is not None
    return running


def stream_types(job_records: JobTables, job: Job) -> list[tuple[str, dict[str, object]]]:
    events = job_records.events_after(job_stream(job.id), 0, 100)
    return [(event.event_type, event.data) for event in events]


def test_a_new_job_is_queued_at_no_attempt_with_its_status_event(job_records: JobTables) -> None:
    job = a_demo(job_records)

    assert (job.kind, job.payload, job.status) == (JobKind.DEMO, {"seconds": 3}, JobStatus.QUEUED)
    assert (job.progress, job.message, job.attempt, job.max_attempts) == (0.0, None, 0, 3)
    assert (job.worker_pid, job.started_at, job.finished_at) == (None, None, None)
    assert job.created_at == STARTED_AT
    assert job_records.by_id(job.id) == job
    assert stream_types(job_records, job) == [("status", {"status": "queued"})]


def test_a_queued_job_starts_once_at_its_next_attempt(job_records: JobTables) -> None:
    job = a_demo(job_records)

    running = started(job_records, job)
    taken = job_records.start(job.id, OTHER_WORKER, LEASE_UNTIL, STARTED_AT)

    assert (running.status, running.attempt, running.worker_pid) == (JobStatus.RUNNING, 1, WORKER)
    assert (running.lease_expires_at, running.started_at) == (LEASE_UNTIL, STARTED_AT)
    assert taken is None
    assert stream_types(job_records, job) == [
        ("status", {"status": "queued"}),
        ("status", {"status": "running"}),
    ]


def test_progress_is_kept_with_its_message_and_an_event(job_records: JobTables) -> None:
    job = started(job_records, a_demo(job_records))

    advanced = job_records.advance(job.id, WORKER, 50.0, "Counted 1 of 2", {"count": 1})

    assert advanced is not None
    assert (advanced.progress, advanced.message, advanced.cancel_requested_at) == (
        50.0,
        "Counted 1 of 2",
        None,
    )
    assert stream_types(job_records, job)[-1] == (
        "progress",
        {"percent": 50.0, "message": "Counted 1 of 2", "details": {"count": 1}},
    )


def test_a_job_asked_to_stop_tells_its_worker_once(job_records: JobTables) -> None:
    job = started(job_records, a_demo(job_records))
    asked_at = STARTED_AT + timedelta(seconds=5)

    asked = job_records.request_cancel(job.id, asked_at)
    again = job_records.request_cancel(job.id, asked_at + timedelta(seconds=1))
    advanced = job_records.advance(job.id, WORKER, 10.0, "Counted 1 of 10", {})

    assert asked is not None
    assert (asked.status, asked.cancel_requested_at) == (JobStatus.RUNNING, asked_at)
    assert again is None
    assert advanced is not None
    assert advanced.cancel_requested_at == asked_at


def test_a_queued_or_finished_job_is_not_asked_to_stop(job_records: JobTables) -> None:
    queued = a_demo(job_records)

    assert job_records.request_cancel(queued.id, STARTED_AT) is None
    assert job_records.by_id(queued.id) == queued


def test_another_worker_changes_nothing(job_records: JobTables) -> None:
    job = started(job_records, a_demo(job_records))

    later = LEASE_UNTIL + timedelta(seconds=15)
    assert job_records.renew_lease(job.id, OTHER_WORKER, later) is False
    assert job_records.advance(job.id, OTHER_WORKER, 99.0, "Not mine", {}) is None
    assert job_records.finish(job.id, OTHER_WORKER, JobStatus.SUCCEEDED, STARTED_AT) is None
    assert job_records.requeue(job.id, OTHER_WORKER) is None
    assert job_records.by_id(job.id) == job
    assert job_records.renew_lease(job.id, WORKER, later) is True
    renewed = job_records.by_id(job.id)
    assert renewed is not None
    assert renewed.lease_expires_at == later


def test_a_running_job_ends_once_with_its_result(job_records: JobTables) -> None:
    job = started(job_records, a_demo(job_records))
    ended_at = STARTED_AT + timedelta(seconds=3)

    ended = job_records.finish(job.id, WORKER, JobStatus.SUCCEEDED, ended_at, result={"counted": 3})
    again = job_records.finish(job.id, WORKER, JobStatus.FAILED, ended_at, error="Late")

    assert ended is not None
    assert (ended.status, ended.result, ended.error, ended.finished_at) == (
        JobStatus.SUCCEEDED,
        {"counted": 3},
        None,
        ended_at,
    )
    assert again is None
    assert stream_types(job_records, job)[-1] == ("status", {"status": "succeeded"})


def test_a_job_fails_with_its_error(job_records: JobTables) -> None:
    job = started(job_records, a_demo(job_records))

    failed = job_records.finish(job.id, WORKER, JobStatus.FAILED, STARTED_AT, error="It broke")

    assert failed is not None
    assert (failed.status, failed.result, failed.error) == (JobStatus.FAILED, None, "It broke")


def test_a_queued_job_is_cancelled_before_it_starts(job_records: JobTables) -> None:
    queued = a_demo(job_records)
    running = started(job_records, a_demo(job_records))

    cancelled = job_records.cancel_queued(queued.id, STARTED_AT)

    assert cancelled is not None
    assert (cancelled.status, cancelled.finished_at) == (JobStatus.CANCELLED, STARTED_AT)
    assert job_records.start(queued.id, WORKER, LEASE_UNTIL, STARTED_AT) is None
    assert job_records.cancel_queued(running.id, STARTED_AT) is None
    assert job_records.finish(queued.id, WORKER, JobStatus.SUCCEEDED, STARTED_AT) is None
    assert stream_types(job_records, queued)[-1] == ("status", {"status": "cancelled"})


def test_a_requeued_job_starts_again_from_the_start_keeping_its_attempts(
    job_records: JobTables,
) -> None:
    job = started(job_records, a_demo(job_records))
    job_records.advance(job.id, WORKER, 50.0, "Counted 1 of 2", {})

    requeued = job_records.requeue(job.id, WORKER)
    again = started(job_records, job, OTHER_WORKER)

    assert requeued is not None
    assert (requeued.status, requeued.attempt, requeued.worker_pid) == (JobStatus.QUEUED, 1, None)
    assert (requeued.progress, requeued.message, requeued.lease_expires_at) == (0.0, None, None)
    assert (again.attempt, again.worker_pid) == (2, OTHER_WORKER)
    assert job_records.requeue(job.id, WORKER) is None


def test_events_come_in_order_after_the_last_one_seen_up_to_a_limit(
    job_records: JobTables,
) -> None:
    job = started(job_records, a_demo(job_records))
    for count in (1, 2, 3):
        job_records.advance(job.id, WORKER, count * 25.0, f"Counted {count} of 4", {})
    other = a_demo(job_records)

    every = job_records.events_after(job_stream(job.id), 0, 100)
    after_second = job_records.events_after(job_stream(job.id), every[1].id, 2)

    assert [event.event_type for event in every] == [
        "status",
        "status",
        "progress",
        "progress",
        "progress",
    ]
    assert [event.id for event in every] == sorted(event.id for event in every)
    assert {event.stream_id for event in every} == {job_stream(job.id)}
    assert after_second == every[2:4]
    assert job_records.events_after(job_stream(job.id), every[-1].id, 100) == ()
    assert len(job_records.events_after(job_stream(other.id), 0, 100)) == 1


def test_recent_jobs_come_newest_first_and_jobs_by_status_oldest_first(
    job_records: JobTables,
) -> None:
    jobs = [
        job_records.add(JobKind.DEMO, {"seconds": 1}, 3, STARTED_AT + timedelta(minutes=minute))
        for minute in range(4)
    ]
    started(job_records, jobs[1])

    assert [job.id for job in job_records.recent(3)] == [jobs[3].id, jobs[2].id, jobs[1].id]
    assert [job.id for job in job_records.with_status(JobStatus.QUEUED)] == [
        jobs[0].id,
        jobs[2].id,
        jobs[3].id,
    ]
    assert [job.id for job in job_records.with_status(JobStatus.RUNNING)] == [jobs[1].id]


def test_a_job_no_one_made_is_none(job_records: JobTables) -> None:
    assert job_records.by_id("0199a0c0-0000-7000-8000-000000000000") is None


@pytest.mark.parametrize("payload", [{}, {"seconds": 60, "note": "kept as given"}])
def test_a_job_keeps_its_payload_as_given(
    job_records: JobTables, payload: dict[str, object]
) -> None:
    job = job_records.add(JobKind.DEMO, payload, 1, STARTED_AT)

    assert job_records.by_id(job.id) == job
    assert job.payload == payload
