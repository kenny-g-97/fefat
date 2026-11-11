"""The local dispatcher (step 4.4, `01-architecture.md` sections 6 and 10, D-16, D-90): a
`concurrent.futures.ProcessPoolExecutor` of spawned processes, the only start method Windows has
and the one Linux is asked for here, sized by `config.toml`'s `process_pool_size`, each process
running `fefat_app.jobs.worker.run_job`; and a reaper, a thread of the server's that every
`reaper_period_seconds` ends the workers that stopped renewing their leases, queueing their jobs
again while they have attempts left, ends the workers of the jobs asked to stop that ran on past
the grace, and submits the queued jobs no worker was given, as after a restart."""

import logging
import multiprocessing
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from datetime import datetime, timedelta
from functools import partial

import psutil
from sqlalchemy.exc import OperationalError

from fefat.config import FefatPaths
from fefat.market.calendar import counted
from fefat_app.job_models import Job, JobStatus
from fefat_app.jobs.worker import JobTimings, run_job
from fefat_app.ports import Clock, JobRecords

LOG = logging.getLogger("fefat_app.jobs")
MOST_WORKERS = 61
"""The most workers the pool runs: CPython's pool refuses more on Windows, which waits on at most
63 handles at once, two of them the pool's own; a machine of 64 cores or more stays at it."""
CLOCK_TICK = timedelta(milliseconds=16)
"""How late a job's start can read the time: Python 3.12 reads Windows' clock in ticks of up to
15.6 ms, while the system records a process's creation precisely, so a worker made a moment
before its job started could otherwise count as made after it (the Phase 4 exit)."""


class LocalDispatcher:
    """`Dispatcher` over a pool of `workers` processes that run the jobs of the database of
    `paths`, which `records` reads too, in the folders of `paths`; no process starts before the
    first job does."""

    def __init__(
        self,
        records: JobRecords,
        paths: FefatPaths,
        clock: Clock,
        timings: JobTimings,
        workers: int,
    ) -> None:
        self.records = records
        self.paths = paths
        self.clock = clock
        self.timings = timings
        self.workers = workers
        self._lock = threading.Lock()
        self._pool: ProcessPoolExecutor | None = None
        self._submitted: dict[str, Future[None]] = {}
        self._stopped = threading.Event()
        self._reaper: threading.Thread | None = None
        self._last_sweep: datetime | None = None
        self._woke_at: datetime | None = None

    def start(self) -> None:
        self._stopped.clear()
        self._reaper = threading.Thread(
            target=self._reap_until_closed, name="jobs' reaper", daemon=True
        )
        self._reaper.start()

    def submit(self, job_id: str) -> None:
        with self._lock:
            try:
                future = self._opened_pool().submit(run_job, job_id, self.paths, self.timings)
            except BrokenProcessPool:
                self._opened_pool().shutdown(wait=False)
                self._pool = None
                future = self._opened_pool().submit(run_job, job_id, self.paths, self.timings)
            self._submitted[job_id] = future
        future.add_done_callback(partial(self._forget, job_id))

    def close(self) -> None:
        """Stop the reaper, kill every process of the server's own, which are the pool's
        workers, and shut the pool down; a kill, since a stopped process on Linux and macOS
        holds a polite end until it continues, while the shutdown waits for it.

        shortcut: a running job's worker is ended rather than waited for, and its job is queued
        again when the server starts next, its attempt spent; a drain that waits for short jobs
        when jobs get long (`BACKLOG.md`)."""
        self._stopped.set()
        if self._reaper is not None:
            self._reaper.join()
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is None:
            return
        for worker in multiprocessing.active_children():
            worker.kill()
        pool.shutdown(wait=True, cancel_futures=True)

    def sweep(self) -> None:
        """Reap the running jobs, then submit the queued jobs no worker was given; a running job's
        row the reaper cannot read or change is logged and passed over, so that it holds up no
        other. For a lease after a gap longer than a lease since the last sweep ended, as when the
        PC slept, the sweeps leave the running jobs to their workers, whose heartbeats wake with it
        and renew the leases; a sweep that the database's busy timeouts made long is no gap."""
        now = self.clock()
        lease = timedelta(seconds=self.timings.lease_seconds)
        if self._last_sweep is not None and now - self._last_sweep > lease:
            self._woke_at = now
        try:
            self._swept(now, self._woke_at is not None and now - self._woke_at < lease)
        finally:
            self._last_sweep = self.clock()

    def _swept(self, now: datetime, waking: bool) -> None:
        running = () if waking else self.records.with_status(JobStatus.RUNNING)
        for job in running:
            try:
                self._reap(job, now)
            except (ValueError, OperationalError):
                LOG.exception("The jobs' reaper passed over the job %s.", job.id)
        queued = self.records.with_status(JobStatus.QUEUED)
        with self._lock:
            unsubmitted = [job.id for job in queued if job.id not in self._submitted]
        for job_id in unsubmitted:
            self.submit(job_id)

    def _reap(self, job: Job, now: datetime) -> None:
        """End `job` where it was asked to stop and ran on past the grace, or where its lease ran
        out, then end its worker; the job first, so that a worker that ended the job itself in
        the meantime, and may run another by now, runs on. Where the database refuses the change,
        held past its busy timeout, as by a worker hung inside one of its own writes, which no
        wait outlasts, the worker is ended first and the change made then."""
        worker_pid, lease_expires_at, started_at = (
            job.worker_pid,
            job.lease_expires_at,
            job.started_at,
        )
        if worker_pid is None or lease_expires_at is None or started_at is None:
            raise ValueError(
                f"Expected the running job {job.id} with a worker, a lease, and a start, "
                f"got {worker_pid}, {lease_expires_at}, and {started_at}."
            )
        asked_to_stop = job.cancel_requested_at
        grace = timedelta(seconds=self.timings.cancel_grace_seconds)
        past_grace = asked_to_stop is not None and now - asked_to_stop >= grace
        if not past_grace and lease_expires_at >= now:
            return
        try:
            ended = self._ended(job, worker_pid, now)
        except OperationalError:
            _kill_worker(worker_pid, started_at)
            ended = self._ended(job, worker_pid, now)
        if ended is None:
            return
        LOG.info("Ending the worker %s of job %s, now %s.", worker_pid, job.id, ended.status)
        _kill_worker(worker_pid, started_at)
        if ended.status == JobStatus.QUEUED:
            self.submit(job.id)

    def _ended(self, job: Job, worker_pid: int, now: datetime) -> Job | None:
        """`job` cancelled where it was asked to stop, queued again while it has attempts left,
        or failed after its last; None where its worker changed it first."""
        if job.cancel_requested_at is not None:
            return self.records.finish(job.id, worker_pid, JobStatus.CANCELLED, now)
        if job.attempt < job.max_attempts:
            return self.records.requeue(job.id, worker_pid)
        reason = (
            f"The worker {worker_pid} stopped answering after {counted(job.attempt, 'attempt')}."
        )
        return self.records.finish(job.id, worker_pid, JobStatus.FAILED, now, error=reason)

    def _reap_until_closed(self) -> None:
        while not self._stopped.wait(self.timings.reaper_period_seconds):
            try:
                self.sweep()
            except Exception:
                LOG.exception("The jobs' reaper failed, and tries again at its next round.")

    def _opened_pool(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=min(self.workers, MOST_WORKERS),
                mp_context=multiprocessing.get_context("spawn"),
            )
        return self._pool

    def _forget(self, job_id: str, future: Future[None]) -> None:
        """Drop `future`, run or failed, so that a sweep submits its job again if it is still
        queued, as its pool broke before a worker took it. It takes no lock: CPython's pool runs it
        while it holds its own lock, which a submit takes under the dispatcher's, so that waiting
        for the dispatcher's here could wait for ever; at worst a job is submitted twice, and the
        second worker's start refuses it."""
        if self._submitted.get(job_id) is future:
            self._submitted.pop(job_id, None)
        if not future.cancelled() and future.exception() is not None:
            LOG.warning("The pool gave up the job %s: %r", job_id, future.exception())


def _kill_worker(worker_pid: int, started_at: datetime) -> None:
    """Kill the worker `worker_pid` of a job that started at `started_at`, one of this process's
    own children made before the job started: Windows soon gives an ended worker's pid to a new
    process, which may be a new worker of the pool. A kill rather than a polite end, which a
    hung worker stopped on Linux or macOS would hold until it continued: the step's hard kill.

    shortcut: the pool marks itself broken when one of its workers ends, ending the others, whose
    jobs the reaper queues again with an attempt spent, so that ends of other jobs' workers can
    fail a job that never misbehaved; one process per job when step 5.3 runs backtests side by
    side (`BACKLOG.md`)."""
    for worker in multiprocessing.active_children():
        if worker.pid == worker_pid and _made_before(worker_pid, started_at):
            worker.kill()


def _made_before(pid: int, instant: datetime) -> bool:
    """Whether the process `pid` was made before `instant`, read up to `CLOCK_TICK` late; not
    where it has ended since."""
    try:
        return psutil.Process(pid).create_time() <= (instant + CLOCK_TICK).timestamp()
    except psutil.NoSuchProcess:
        return False
