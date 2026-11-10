"""The local dispatcher of step 4.4 (`01-architecture.md` section 6, D-90) on a real pool of
spawned processes and the system's clock, with short leases: a submitted demo runs in a worker
of the pool; a request to stop ends it at its next report; a killed worker's job is queued again
until its attempts are spent, then fails (Done means 1); and the reaper ends a worker that runs on
past the grace after a request to stop, or that stopped renewing its lease. Each wait has a
deadline, since a spawned worker takes a second or more to start on Windows."""

import multiprocessing
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from functools import partial
from multiprocessing.process import BaseProcess
from typing import Any

import psutil
import pytest
from sqlalchemy.orm import Session

from fefat.config import resolve_paths
from fefat_app.database.job_records import JobTables
from fefat_app.database.models import JobRow
from fefat_app.execution import ExecutionLimits, PythonSnippetSpec
from fefat_app.jobs.dispatcher import LocalDispatcher, _made_before
from fefat_app.jobs.worker import JobTimings
from fefat_app.ports import Job, JobEnd, JobKind, JobStatus, job_stream
from local_server import SettableClock
from write_lock import hung_inside_a_write

TEST_TIMINGS = JobTimings(
    lease_seconds=3, heartbeat_seconds=0.5, reaper_period_seconds=0.5, cancel_grace_seconds=1
)
DEADLINE_SECONDS = 60


def a_dispatcher(job_records: JobTables) -> LocalDispatcher:
    return LocalDispatcher(
        job_records,
        resolve_paths(os.environ),
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


def suspended_outside_a_write(worker: psutil.Process) -> None:
    """Suspend `worker` at a moment it holds no write of the database, as a worker that hangs in
    its work does: one suspended inside its heartbeat's or its report's transaction would keep
    the database's write lock, and with it the reaper from queueing its job again (`BACKLOG.md`,
    a worker hung inside a write), so such a suspension is let go and tried again."""
    database_file = resolve_paths(os.environ).database_file
    deadline = time.monotonic() + DEADLINE_SECONDS
    while time.monotonic() < deadline:
        worker.suspend()
        time.sleep(0.05)
        probe = sqlite3.connect(database_file, timeout=0)
        try:
            probe.execute("BEGIN IMMEDIATE")
            probe.rollback()
            return
        except sqlite3.OperationalError:
            worker.resume()
        finally:
            probe.close()
        time.sleep(0.05)
    raise AssertionError(f"Expected the worker {worker.pid} suspended outside a write.")


def worker_of(pid: int | None) -> BaseProcess:
    workers = [child for child in multiprocessing.active_children() if child.pid == pid]
    assert len(workers) == 1, f"Expected one worker of pid {pid}, got {workers}."
    return workers[0]


class WorkerEndsFirst(JobTables):
    """The records of a race the reaper loses: each job's worker ends it, a moment before the
    reaper's own change of it."""

    def finish(
        self,
        job_id: str,
        worker_pid: int,
        end: JobEnd,
        now: datetime,
        *,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> Job | None:
        super().finish(job_id, worker_pid, JobStatus.SUCCEEDED, now, result={})
        return super().finish(job_id, worker_pid, end, now, result=result, error=error)


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


def test_a_snippet_job_runs_its_runner_from_a_worker_of_the_pool(
    dispatcher: LocalDispatcher, job_records: JobTables
) -> None:
    # The Phase 4 exit's step review: the executions ran as jobs in the tests' own process alone,
    # while a worker of the pool starts its runners from a spawned interpreter of its own.
    limits = ExecutionLimits(timeout_seconds=60, memory_bytes=8 * 1024**3)
    snippet = PythonSnippetSpec(code="print(6 * 7)\n", bars=None, limits=limits)
    job = job_records.add(
        JobKind.PYTHON_SNIPPET, snippet.model_dump(mode="json"), 3, datetime.now(UTC)
    )

    dispatcher.submit(job.id)
    ended = waited_for(
        job_records, job, lambda now: now.status not in (JobStatus.QUEUED, JobStatus.RUNNING)
    )

    assert (ended.status, ended.error) == (JobStatus.SUCCEEDED, None)
    assert ended.result is not None
    assert ended.result["output"] == {"kind": "python_snippet", "stdout_tail": "42\n"}
    assert ended.worker_pid not in (None, os.getpid())


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
    assert ended.error == f"The worker {stand_in.pid} stopped answering after 1 attempt."


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
        resolve_paths(os.environ),
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


def test_a_worker_made_within_a_tick_of_the_clock_before_its_job_started_counts_as_before(
    stand_in: BaseProcess,
) -> None:
    # The Phase 4 exit: Python 3.12 reads Windows' clock in ticks of up to 15.6 ms, while the
    # system records a process's creation precisely, so a job's start read just after its
    # worker was made could come out a few milliseconds before it, 1.5 and 5.6 ms in the runs
    # that failed, and the reaper left the worker running.
    assert stand_in.pid is not None
    created = datetime.fromtimestamp(psutil.Process(stand_in.pid).create_time(), UTC)

    assert _made_before(stand_in.pid, created - timedelta(milliseconds=6))
    assert not _made_before(stand_in.pid, created - timedelta(seconds=1))


def test_a_worker_made_after_its_job_started_is_left_running(
    idle_dispatcher: LocalDispatcher, job_records: JobTables, stand_in: BaseProcess
) -> None:
    # Windows gives an ended worker's pid to a new process soon: the reaper ends only a worker
    # made before the job it reaps started, and changes the job all the same.
    job = a_demo(job_records, seconds=60, max_attempts=1)
    assert stand_in.pid is not None
    before_the_stand_in = datetime.now(UTC) - timedelta(seconds=60)
    job_records.start(job.id, stand_in.pid, before_the_stand_in, before_the_stand_in)

    idle_dispatcher.sweep()
    stand_in.join(1)

    ended = job_records.by_id(job.id)
    assert ended is not None
    assert ended.status == JobStatus.FAILED
    assert stand_in.is_alive()


def test_a_job_its_worker_ended_first_leaves_the_worker_running(
    job_records: JobTables, stand_in: BaseProcess
) -> None:
    # The worker that ended its job may already run another: the reaper ends a worker only
    # once its own change of the job holds.
    racing = LocalDispatcher(
        WorkerEndsFirst(job_records.engine),
        resolve_paths(os.environ),
        partial(datetime.now, UTC),
        TEST_TIMINGS,
        workers=1,
    )
    job = held_by_stand_in(job_records, a_demo(job_records, seconds=60), stand_in, lease=60)
    job_records.request_cancel(job.id, datetime.now(UTC) - timedelta(seconds=5))

    try:
        racing.sweep()
        stand_in.join(1)
    finally:
        racing.close()

    ended = job_records.by_id(job.id)
    assert ended is not None
    assert ended.status == JobStatus.SUCCEEDED
    assert stand_in.is_alive()


def test_a_running_job_the_reaper_cannot_read_holds_up_no_other(
    idle_dispatcher: LocalDispatcher, job_records: JobTables
) -> None:
    # A row changed by hand, running with no worker or lease, is logged and passed over.
    with Session(job_records.engine) as session, session.begin():
        session.add(
            JobRow(
                kind=JobKind.DEMO,
                payload_json={"seconds": 1},
                status=JobStatus.RUNNING,
                progress=0.0,
                attempt=1,
                max_attempts=3,
                created_at=datetime.now(UTC),
            )
        )
    queued = a_demo(job_records, seconds=1)

    idle_dispatcher.sweep()
    ended = waited_for(job_records, queued, lambda now: now.status == JobStatus.SUCCEEDED)

    assert ended.result == {"counted": 1}


def test_the_reaper_queues_a_hung_workers_job_again_in_a_new_worker(
    dispatcher: LocalDispatcher, job_records: JobTables
) -> None:
    # The reaper's own path for a worker that hangs: its lease runs out, the job is queued
    # again, the worker is ended, which breaks the pool, and the job runs again in a new one.
    job = a_demo(job_records, seconds=60, max_attempts=2)
    dispatcher.submit(job.id)
    first = waited_for(job_records, job, lambda now: now.progress > 0)
    assert first.worker_pid is not None

    suspended_outside_a_write(psutil.Process(first.worker_pid))
    second = waited_for(
        job_records,
        job,
        lambda now: now.status == JobStatus.RUNNING and now.attempt == 2,
    )

    assert second.worker_pid not in (None, first.worker_pid)


def test_the_reaper_ends_a_worker_hung_inside_a_write_then_queues_its_job_again(
    idle_dispatcher: LocalDispatcher, job_records: JobTables
) -> None:
    # The Phase 4 exit (`BACKLOG.md`, a worker hung inside a write): a worker that hangs while it
    # holds the database's write lock refused every change of the reaper's, so that its job ran
    # for ever; the reaper now ends such a worker first, then queues its job again.
    spawning = multiprocessing.get_context("spawn")
    go, locked = spawning.Event(), spawning.Event()
    database_file = str(resolve_paths(os.environ).database_file)
    hung = spawning.Process(target=hung_inside_a_write, args=(database_file, go, locked))
    hung.start()
    try:
        job = held_by_stand_in(job_records, a_demo(job_records, seconds=60), hung, lease=-10)
        go.set()
        assert locked.wait(DEADLINE_SECONDS)

        idle_dispatcher.sweep()
        hung.join(DEADLINE_SECONDS)
        ended = hung.exitcode
        again = waited_for(
            job_records,
            job,
            lambda now: now.status == JobStatus.RUNNING and now.attempt == 2,
        )
    finally:
        hung.kill()
        hung.join()

    assert ended is not None
    assert again.worker_pid not in (None, hung.pid)


def test_a_pool_failing_its_futures_never_waits_for_the_dispatchers_lock(
    job_records: JobTables,
) -> None:
    # CPython's pool fails its pending futures, whose callbacks it runs, while it holds its own
    # lock, which a submit takes under the dispatcher's: a callback that waited for the
    # dispatcher's lock would wait for ever, and every later submit with it.
    dispatcher = a_dispatcher(job_records)
    ended: Future[None] = Future()
    ended.set_result(None)
    forgetting = threading.Thread(target=dispatcher._forget, args=("job", ended), daemon=True)

    with dispatcher._lock:
        forgetting.start()
        forgetting.join(5)
        waiting = forgetting.is_alive()

    assert not waiting


def test_a_sweep_after_the_server_slept_leaves_the_workers_to_renew_first(
    job_records: JobTables, stand_in: BaseProcess
) -> None:
    # A PC that slept past a lease wakes the workers and the reaper together: the sweeps for a
    # lease after so long a gap leave the leases to the workers' heartbeats, the next of which
    # can come a reaper's period after the first sweep (the Phase 4 exit's code review); the
    # first sweep a lease after the wake reaps.
    clock = SettableClock(datetime.now(UTC))
    dispatcher = LocalDispatcher(
        job_records,
        resolve_paths(os.environ),
        clock,
        TEST_TIMINGS,
        workers=1,
    )
    job = a_demo(job_records, seconds=60, max_attempts=1)
    held_by_stand_in(job_records, job, stand_in, lease=1)

    try:
        dispatcher.sweep()
        clock.advance(timedelta(hours=1))
        dispatcher.sweep()
        after_the_sleep = job_records.by_id(job.id)
        clock.advance(timedelta(seconds=TEST_TIMINGS.reaper_period_seconds))
        dispatcher.sweep()
        a_period_later = job_records.by_id(job.id)
        clock.advance(timedelta(seconds=TEST_TIMINGS.lease_seconds))
        dispatcher.sweep()
        reaped = job_records.by_id(job.id)
    finally:
        dispatcher.close()

    assert after_the_sleep is not None
    assert after_the_sleep.status == JobStatus.RUNNING
    assert a_period_later is not None
    assert a_period_later.status == JobStatus.RUNNING
    assert reaped is not None
    assert reaped.status == JobStatus.FAILED
