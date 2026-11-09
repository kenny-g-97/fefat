"""A job's run in a worker of step 4.4 (`01-architecture.md` section 6): the worker starts the
queued job, keeps its lease while the work runs, and ends it as the work ends, succeeded with its
result, cancelled at the first report after a request to stop, or failed with the reason; run in
this process here, where the dispatcher's tests run it in the pool's."""

import os
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.exc import OperationalError

from fefat.config import FefatPaths, resolve_paths
from fefat_app.database.job_records import JobTables
from fefat_app.jobs.progress import JobCancelledError, JobProgress
from fefat_app.jobs.worker import JobTimings, run_job
from fefat_app.ports import Job, JobEnd, JobKind, JobStatus, job_stream
from local_server import STARTED_AT

DEADLINE_SECONDS = 30
SERVER_TIMINGS = JobTimings()


def fefat_paths() -> FefatPaths:
    return resolve_paths(os.environ)


def a_demo(job_records: JobTables, payload: dict[str, object]) -> Job:
    return job_records.add(JobKind.DEMO, payload, 3, STARTED_AT)


def ran(job_records: JobTables, job: Job, timings: JobTimings = SERVER_TIMINGS) -> Job:
    run_job(job.id, fefat_paths(), timings)
    ended = job_records.by_id(job.id)
    assert ended is not None
    return ended


def waited_for(job_records: JobTables, job: Job, reached: Callable[[Job], bool]) -> Job:
    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        now = job_records.by_id(job.id)
        assert now is not None
        if reached(now):
            return now
        time.sleep(0.05)
    raise AssertionError(f"Expected the job {job.id} to change within {DEADLINE_SECONDS} s.")


def test_a_worker_runs_a_demo_to_its_end_with_its_progress(job_records: JobTables) -> None:
    # Done means 1: queued, running, two reports, succeeded.
    job = a_demo(job_records, {"seconds": 2})

    ended = ran(job_records, job)

    assert (ended.status, ended.result, ended.progress) == (
        JobStatus.SUCCEEDED,
        {"counted": 2},
        100.0,
    )
    assert (ended.message, ended.attempt, ended.worker_pid) == ("Counted 2 of 2", 1, os.getpid())
    events = job_records.events_after(job_stream(job.id), 0, 100)
    assert [(event.event_type, event.said) for event in events] == [
        ("status", {"status": "queued"}),
        ("status", {"status": "running"}),
        ("progress", {"percent": 50.0, "message": "Counted 1 of 2", "details": {"count": 1}}),
        ("progress", {"percent": 100.0, "message": "Counted 2 of 2", "details": {"count": 2}}),
        ("status", {"status": "succeeded"}),
    ]


def test_a_job_asked_to_stop_ends_cancelled_at_its_next_report(job_records: JobTables) -> None:
    # Done means 1: the request is checked between chunks, the demo's seconds.
    job = a_demo(job_records, {"seconds": 60})
    worker = threading.Thread(target=run_job, args=(job.id, fefat_paths(), JobTimings()))
    worker.start()

    waited_for(job_records, job, lambda now: now.status == JobStatus.RUNNING)
    job_records.request_cancel(job.id, STARTED_AT)
    worker.join(DEADLINE_SECONDS)

    ended = job_records.by_id(job.id)
    assert ended is not None
    assert not worker.is_alive()
    assert ended.status == JobStatus.CANCELLED
    assert ended.progress < 100.0


def test_the_worker_keeps_its_lease_while_the_work_runs(job_records: JobTables) -> None:
    job = a_demo(job_records, {"seconds": 2})

    ended = ran(job_records, job, JobTimings(lease_seconds=1, heartbeat_seconds=0.1))

    assert ended.status == JobStatus.SUCCEEDED
    assert ended.started_at is not None
    assert ended.lease_expires_at is not None
    assert ended.lease_expires_at > ended.started_at + timedelta(seconds=1.5)


def test_a_kind_the_worker_cannot_run_fails_with_the_reason(job_records: JobTables) -> None:
    job = job_records.add(JobKind.BACKTEST, {}, 3, STARTED_AT)

    ended = ran(job_records, job)

    assert ended.status == JobStatus.FAILED
    assert ended.error == (
        "ValueError: Expected a job kind the worker runs (demo, feature_preview, python_snippet), "
        "got backtest."
    )


def test_a_demo_refuses_a_payload_it_cannot_count(job_records: JobTables) -> None:
    job = a_demo(job_records, {"seconds": 0})

    ended = ran(job_records, job)

    assert ended.status == JobStatus.FAILED
    assert ended.error is not None
    assert ended.error.startswith("ValidationError: 1 validation error for DemoPayload")


def test_a_job_another_worker_took_is_left_as_it_is(job_records: JobTables) -> None:
    job = a_demo(job_records, {"seconds": 1})
    taken = job_records.start(job.id, 4242, STARTED_AT + timedelta(seconds=15), STARTED_AT)

    assert ran(job_records, job) == taken


def test_a_report_outside_0_to_100_percent_is_refused(job_records: JobTables) -> None:
    job = a_demo(job_records, {"seconds": 1})
    job_records.start(job.id, os.getpid(), STARTED_AT + timedelta(seconds=15), STARTED_AT)
    progress = JobProgress(job_records, job.id, os.getpid())

    with pytest.raises(ValueError, match="Expected a percent from 0 to 100, got 101"):
        progress.advance(101, "Too far")


def test_a_report_of_a_job_no_longer_held_stops_the_work(job_records: JobTables) -> None:
    job = a_demo(job_records, {"seconds": 1})
    job_records.start(job.id, 4242, STARTED_AT + timedelta(seconds=15), STARTED_AT)

    with pytest.raises(JobCancelledError, match="no longer held"):
        JobProgress(job_records, job.id, os.getpid()).advance(50, "Not mine")


def test_the_lease_outlasts_a_renewal_the_busy_database_refused(
    job_records: JobTables, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A writer that holds the database past the busy timeout refuses one renewal; the next beat
    # renews the lease, so that the reaper never ends a worker that answers.
    renew_lease = JobTables.renew_lease
    refusals = [OperationalError("renew", {}, sqlite3.OperationalError("database is locked"))]

    def busy_once(records: JobTables, job_id: str, worker_pid: int, lease_until: datetime) -> bool:
        if refusals:
            raise refusals.pop()
        return renew_lease(records, job_id, worker_pid, lease_until)

    monkeypatch.setattr(JobTables, "renew_lease", busy_once)
    job = a_demo(job_records, {"seconds": 2})

    ended = ran(job_records, job, JobTimings(lease_seconds=1, heartbeat_seconds=0.1))

    assert refusals == []
    assert ended.started_at is not None
    assert ended.lease_expires_at is not None
    assert ended.lease_expires_at > ended.started_at + timedelta(seconds=1.5)


def test_a_report_the_busy_database_refused_is_skipped_and_the_work_goes_on(
    job_records: JobTables, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The next report says how far the work came, and checks for a request to stop again.
    advance = JobTables.advance
    refusals = [OperationalError("advance", {}, sqlite3.OperationalError("database is locked"))]

    def busy_once(
        records: JobTables,
        job_id: str,
        worker_pid: int,
        percent: float,
        message: str,
        details: Mapping[str, Any],
    ) -> Job | None:
        if refusals:
            raise refusals.pop()
        return advance(records, job_id, worker_pid, percent, message, details)

    monkeypatch.setattr(JobTables, "advance", busy_once)
    job = a_demo(job_records, {"seconds": 2})

    ended = ran(job_records, job)

    assert refusals == []
    assert (ended.status, ended.progress, ended.result) == (
        JobStatus.SUCCEEDED,
        100.0,
        {"counted": 2},
    )


def test_an_end_the_busy_database_refused_is_tried_again(
    job_records: JobTables, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A job whose end was never written would run on as running until its lease ran out.
    finish = JobTables.finish
    refusals = [OperationalError("finish", {}, sqlite3.OperationalError("database is locked"))]

    def busy_once(
        records: JobTables,
        job_id: str,
        worker_pid: int,
        end: JobEnd,
        now: datetime,
        *,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> Job | None:
        if refusals:
            raise refusals.pop()
        return finish(records, job_id, worker_pid, end, now, result=result, error=error)

    monkeypatch.setattr(JobTables, "finish", busy_once)
    job = a_demo(job_records, {"seconds": 1})

    ended = ran(job_records, job)

    assert refusals == []
    assert (ended.status, ended.result) == (JobStatus.SUCCEEDED, {"counted": 1})
