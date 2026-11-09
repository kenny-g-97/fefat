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
from pathlib import Path

from fefat_app.jobs.worker import JobTimings, run_job
from fefat_app.ports import Clock, Job, JobRecords, JobStatus

LOG = logging.getLogger("fefat_app.jobs")


class LocalDispatcher:
    """`Dispatcher` over a pool of `workers` processes that run the jobs of the database
    `database_file`, which `records` reads too; no process starts before the first job does."""

    def __init__(
        self,
        records: JobRecords,
        database_file: Path,
        clock: Clock,
        timings: JobTimings,
        workers: int,
    ) -> None:
        self.records = records
        self.database_file = database_file
        self.clock = clock
        self.timings = timings
        self.workers = workers
        self._lock = threading.Lock()
        self._pool: ProcessPoolExecutor | None = None
        self._submitted: dict[str, Future[None]] = {}
        self._stopped = threading.Event()
        self._reaper: threading.Thread | None = None

    def start(self) -> None:
        self._stopped.clear()
        self._reaper = threading.Thread(
            target=self._reap_until_closed, name="jobs' reaper", daemon=True
        )
        self._reaper.start()

    def submit(self, job_id: str) -> None:
        with self._lock:
            try:
                future = self._opened_pool().submit(
                    run_job, job_id, self.database_file, self.timings
                )
            except BrokenProcessPool:
                self._opened_pool().shutdown(wait=False)
                self._pool = None
                future = self._opened_pool().submit(
                    run_job, job_id, self.database_file, self.timings
                )
            self._submitted[job_id] = future
        future.add_done_callback(partial(self._forget, job_id))

    def close(self) -> None:
        """Stop the reaper, end every process of the server's own, which are the pool's
        workers, and shut the pool down.

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
            worker.terminate()
        pool.shutdown(wait=True, cancel_futures=True)

    def sweep(self) -> None:
        """Reap the running jobs, then submit the queued jobs no worker was given."""
        now = self.clock()
        for job in self.records.with_status(JobStatus.RUNNING):
            self._reap(job, now)
        queued = self.records.with_status(JobStatus.QUEUED)
        with self._lock:
            unsubmitted = [job.id for job in queued if job.id not in self._submitted]
        for job_id in unsubmitted:
            self.submit(job_id)

    def _reap(self, job: Job, now: datetime) -> None:
        """End `job`'s worker where it was asked to stop past the grace, or where its lease ran
        out, and end the job, or queue it again while it has attempts left."""
        worker_pid, lease_expires_at = job.worker_pid, job.lease_expires_at
        if worker_pid is None or lease_expires_at is None:
            raise ValueError(
                f"Expected the running job {job.id} with a worker and a lease, "
                f"got {worker_pid} and {lease_expires_at}."
            )
        grace = timedelta(seconds=self.timings.cancel_grace_seconds)
        asked_to_stop = job.cancel_requested_at
        if asked_to_stop is not None and now - asked_to_stop >= grace:
            LOG.info("Ending the worker %s of job %s, asked to stop.", worker_pid, job.id)
            _terminate(worker_pid)
            self.records.finish(job.id, worker_pid, JobStatus.CANCELLED, now)
            return
        if lease_expires_at >= now:
            return
        LOG.info("Ending the worker %s of job %s, which stopped answering.", worker_pid, job.id)
        _terminate(worker_pid)
        if asked_to_stop is not None:
            self.records.finish(job.id, worker_pid, JobStatus.CANCELLED, now)
        elif job.attempt < job.max_attempts:
            if self.records.requeue(job.id, worker_pid) is not None:
                self.submit(job.id)
        else:
            reason = f"The worker {worker_pid} stopped answering after {job.attempt} attempts."
            self.records.finish(job.id, worker_pid, JobStatus.FAILED, now, error=reason)

    def _reap_until_closed(self) -> None:
        while not self._stopped.wait(self.timings.reaper_period_seconds):
            try:
                self.sweep()
            except Exception:
                LOG.exception("The jobs' reaper failed, and tries again at its next round.")

    def _opened_pool(self) -> ProcessPoolExecutor:
        if self._pool is None:
            self._pool = ProcessPoolExecutor(
                max_workers=self.workers, mp_context=multiprocessing.get_context("spawn")
            )
        return self._pool

    def _forget(self, job_id: str, future: Future[None]) -> None:
        """Drop `future`, run or failed, so that a sweep submits its job again if it is still
        queued, as its pool broke before a worker took it."""
        with self._lock:
            if self._submitted.get(job_id) is future:
                del self._submitted[job_id]
        if not future.cancelled() and future.exception() is not None:
            LOG.warning("The pool gave up the job %s: %r", job_id, future.exception())


def _terminate(worker_pid: int) -> None:
    """End the worker `worker_pid`, one of this process's own children, by its handle rather
    than its pid, which the system may have given another process since.

    shortcut: the pool marks itself broken when one of its workers ends, ending the others, whose
    jobs the reaper queues again with an attempt spent; one process per job when step 5.3 runs
    backtests side by side (`BACKLOG.md`)."""
    for worker in multiprocessing.active_children():
        if worker.pid == worker_pid:
            worker.terminate()
