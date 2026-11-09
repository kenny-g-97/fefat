"""The local dispatcher of step 4.4 (`01-architecture.md` section 6, D-90) on a real pool of
spawned processes and the system's clock, with short leases: a submitted demo runs in a worker
of the pool; a request to stop ends it at its next report; a killed worker's job is queued again
until its attempts are spent, then fails (Done means 1); and the reaper ends a worker that runs on
past the grace after a request to stop, or that stopped renewing its lease. Each wait has a
deadline, since a spawned worker takes a second or more to start on Windows."""

import multiprocessing
import os
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from functools import partial
from multiprocessing.process import BaseProcess

import pytest

from fefat.config import resolve_paths
from fefat_app.database.job_records import JobTables
from fefat_app.jobs.dispatcher import LocalDispatcher
from fefat_app.jobs.worker import JobTimings
from fefat_app.ports import Job, JobKind, JobStatus, job_stream

TEST_TIMINGS = JobTimings(
    lease_seconds=3, heartbeat_seconds=0.5, reaper_period_seconds=0.5, cancel_grace_seconds=1
)
DEADLINE_SECONDS = 60


def a_dispatcher(job_records: JobTables) -> LocalDispatcher:
    return LocalDispatcher(
        job_records,
        resolve_paths(os.environ).database_file,
        partial(datetime.now, UTC),
        TEST_TIMINGS,
        workers=1,
    )


@pytest.fixture
def dispatcher(job_records: JobTables) -> Iterator[LocalDispatcher]:
    """A dispatcher reaping, as the server starts it, and closed after the test."""
    started = a_dispatcher(job_records)
    started.start()
    try:
        yield started
    finally:
        started.close()


@pytest.fixture
def idle_dispatcher(job_records: JobTables) -> Iterator[LocalDispatcher]:
    """A dispatcher whose reaper the test runs itself, through `sweep`."""
    idle = a_dispatcher(job_records)
    try:
        yield idle
    finally:
        idle.close()


@pytest.fixture
def stand_in() -> Iterator[BaseProcess]:
    """A process of this one's that sleeps, standing in for a worker the reaper must end."""
    sleeper = multiprocessing.get_context("spawn").Process(target=time.sleep, args=(600,))
    sleeper.start()
    try:
        yield sleeper
    finally:
        sleeper.kill()
        sleeper.join()


def waited_for(job_records: JobTables, job: Job, reached: Callable[[Job], bool]) -> Job:
    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        now = job_records.by_id(job.id)
        assert now is not None
        if reached(now):
            return now
        time.sleep(0.1)
    raise AssertionError(f"Expected the job {job.id} to change within {DEADLINE_SECONDS} s.")


def a_demo(job_records: JobTables, seconds: int, max_attempts: int = 3) -> Job:
    return job_records.add(JobKind.DEMO, {"seconds": seconds}, max_attempts, datetime.now(UTC))


def worker_of(pid: int | None) -> BaseProcess:
    workers = [child for child in multiprocessing.active_children() if child.pid == pid]
    assert len(workers) == 1, f"Expected one worker of pid {pid}, got {workers}."
    return workers[0]


def held_by_stand_in(job_records: JobTables, job: Job, stand_in: BaseProcess, lease: float) -> Job:
    """`job` running in `stand_in`, its lease ending `lease` seconds from now."""
    assert stand_in.pid is not None
    now = datetime.now(UTC)
    running = job_records.start(job.id, stand_in.pid, now + timedelta(seconds=lease), now)
    assert running is not None
    return running


def test_a_submitted_demo_runs_in_a_worker_of_the_pool(
    dispatcher: LocalDispatcher, job_records: JobTables
) -> None:
    # Done means 1.
    job = a_demo(job_records, seconds=2)

    dispatcher.submit(job.id)
    ended = waited_for(job_records, job, lambda now: now.status == JobStatus.SUCCEEDED)

    assert (ended.result, ended.progress, ended.attempt) == ({"counted": 2}, 100.0, 1)
    assert ended.worker_pid not in (None, os.getpid())
    reports = job_records.events_after(job_stream(job.id), 0, 100)
    assert [event.said["percent"] for event in reports if event.event_type == "progress"] == [
        50.0,
        100.0,
    ]


def test_cancel_stops_a_running_demo(dispatcher: LocalDispatcher, job_records: JobTables) -> None:
    # Done means 1: cancellation.
    job = a_demo(job_records, seconds=60)
    dispatcher.submit(job.id)
    waited_for(job_records, job, lambda now: now.progress > 0)

    job_records.request_cancel(job.id, datetime.now(UTC))
    ended = waited_for(job_records, job, lambda now: now.status == JobStatus.CANCELLED)

    assert ended.progress < 100.0
    assert ended.finished_at is not None


def test_a_killed_workers_job_is_queued_again_up_to_its_attempts_then_fails(
    dispatcher: LocalDispatcher, job_records: JobTables
) -> None:
    # Done means 1: requeue after a killed worker, up to max attempts.
    job = a_demo(job_records, seconds=60, max_attempts=2)
    dispatcher.submit(job.id)
    first = waited_for(job_records, job, lambda now: now.status == JobStatus.RUNNING)

    worker_of(first.worker_pid).kill()
    second = waited_for(
        job_records,
        job,
        lambda now: now.status == JobStatus.RUNNING and now.attempt == 2,
    )
    worker_of(second.worker_pid).kill()
    ended = waited_for(job_records, job, lambda now: now.status == JobStatus.FAILED)

    assert first.attempt == 1
    assert second.worker_pid != first.worker_pid
    assert ended.attempt == 2
    assert ended.error == f"The worker {second.worker_pid} stopped answering after 2 attempts."
    statuses = [
        event.said["status"]
        for event in job_records.events_after(job_stream(job.id), 0, 1000)
        if event.event_type == "status"
    ]
    assert statuses == ["queued", "running", "queued", "running", "failed"]


def test_a_job_asked_to_stop_is_ended_after_the_grace_with_its_worker(
    idle_dispatcher: LocalDispatcher, job_records: JobTables, stand_in: BaseProcess
) -> None:
    # The hard kill: the worker never reported after the request to stop.
    job = held_by_stand_in(job_records, a_demo(job_records, seconds=60), stand_in, lease=60)
    job_records.request_cancel(job.id, datetime.now(UTC) - timedelta(seconds=5))

    idle_dispatcher.sweep()
    stand_in.join(DEADLINE_SECONDS)

    ended = job_records.by_id(job.id)
    assert ended is not None
    assert not stand_in.is_alive()
    assert ended.status == JobStatus.CANCELLED


def test_a_job_asked_to_stop_runs_on_within_the_grace(
    idle_dispatcher: LocalDispatcher, job_records: JobTables, stand_in: BaseProcess
) -> None:
    job = held_by_stand_in(job_records, a_demo(job_records, seconds=60), stand_in, lease=60)
    job_records.request_cancel(job.id, datetime.now(UTC))

    idle_dispatcher.sweep()

    still = job_records.by_id(job.id)
    assert still is not None
    assert stand_in.is_alive()
    assert still.status == JobStatus.RUNNING


def test_a_worker_that_stopped_renewing_its_lease_is_ended_with_its_last_attempt(
    idle_dispatcher: LocalDispatcher, job_records: JobTables, stand_in: BaseProcess
) -> None:
    job = a_demo(job_records, seconds=60, max_attempts=1)
    held_by_stand_in(job_records, job, stand_in, lease=-1)

    idle_dispatcher.sweep()
    stand_in.join(DEADLINE_SECONDS)

    ended = job_records.by_id(job.id)
    assert ended is not None
    assert not stand_in.is_alive()
    assert ended.status == JobStatus.FAILED
    assert ended.error == f"The worker {stand_in.pid} stopped answering after 1 attempts."


def test_a_job_asked_to_stop_whose_worker_stopped_answering_is_cancelled(
    idle_dispatcher: LocalDispatcher, job_records: JobTables, stand_in: BaseProcess
) -> None:
    job = held_by_stand_in(job_records, a_demo(job_records, seconds=60), stand_in, lease=-1)
    job_records.request_cancel(job.id, datetime.now(UTC))

    idle_dispatcher.sweep()

    ended = job_records.by_id(job.id)
    assert ended is not None
    assert ended.status == JobStatus.CANCELLED


def test_a_queued_job_no_worker_was_given_runs_after_a_sweep(
    idle_dispatcher: LocalDispatcher, job_records: JobTables
) -> None:
    # As after a restart of the server, whose pool lost what it had queued.
    job = a_demo(job_records, seconds=1)

    idle_dispatcher.sweep()
    ended = waited_for(job_records, job, lambda now: now.status == JobStatus.SUCCEEDED)

    assert ended.result == {"counted": 1}


def test_closing_ends_a_running_worker(job_records: JobTables) -> None:
    dispatcher = a_dispatcher(job_records)
    job = a_demo(job_records, seconds=60)
    dispatcher.submit(job.id)
    running = waited_for(job_records, job, lambda now: now.status == JobStatus.RUNNING)
    worker = worker_of(running.worker_pid)

    dispatcher.close()
    worker.join(DEADLINE_SECONDS)

    assert not worker.is_alive()


def test_a_pool_wider_than_windows_allows_still_runs_its_jobs(job_records: JobTables) -> None:
    # CPython's pool refuses more than 61 workers on Windows, where a 64-core machine's default
    # would ask for 62 (D-90).
    dispatcher = LocalDispatcher(
        job_records,
        resolve_paths(os.environ).database_file,
        partial(datetime.now, UTC),
        TEST_TIMINGS,
        workers=64,
    )
    job = a_demo(job_records, seconds=1)
    try:
        dispatcher.submit(job.id)
        ended = waited_for(job_records, job, lambda now: now.status == JobStatus.SUCCEEDED)
    finally:
        dispatcher.close()

    assert ended.result == {"counted": 1}
