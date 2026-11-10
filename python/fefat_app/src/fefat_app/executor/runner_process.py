"""A runner as the executor sees it (step 4.5): a process of `sys.executable` running
`python -P -m fefat_app.executor`, which puts no working folder on its import path, given one
execution's folder at its start or, warm, sent each folder on its stdin; contained from its first
line, on Windows in a Job Object that limits its memory, which it joins while suspended, and
elsewhere in a session of its own, the runner limiting its own memory; its lines of progress read
by a thread of their own, so that the executor waits for them no longer than the execution's
deadline, and asks between them whether the execution runs on; its stderr, and what the trader's
code prints from C or Rust, in a log of its own under `FefatPaths.executions_dir`; and stopped
with every process it started, at a timeout, a failure, a request to stop, or the end of its
work."""

import contextlib
import logging
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import IO, BinaryIO

import psutil
from pydantic import ValidationError

from fefat.config import FefatPaths
from fefat_app.execution import ExecutionProgress, ProgressReport, StopCheck
from fefat_app.executor.environment import scrubbed_environment
from fefat_app.executor.protocol import END_OF_EXECUTION, RunnerOutputError, problems

LOG = logging.getLogger("fefat_app.executor")
RUNNER_MODULE = "fefat_app.executor"
CREATE_SUSPENDED = 0x00000004
"""Windows' flag that starts a process with its first thread suspended, until it is resumed."""
CHECK_SECONDS = 1.0
"""How long the executor waits for a report before it asks whether the execution runs on."""
LOG_TAIL_BYTES = 2000
"""How much of a runner's log a failure quotes, from its end."""
READER_SECONDS = 5.0
"""How long a stopped runner's reader may take to see the end of its output."""
REMOVAL_SECONDS = 2.0
"""How long the executor tries to remove what a runner it stopped held, its log and its working
folder, which Windows lets go of some milliseconds after the runner has ended."""
LEFT_SECONDS = 24 * 3600
"""How long ago a runner's log or an execution's folder last changed for the server's start to
take it for one left behind, since a notebook's own executor may use the folder meanwhile."""


class RunnerEnd(StrEnum):
    """Why the executor stopped reading a runner's progress: the execution's result is in its
    folder, the runner ended first, or the execution's deadline passed."""

    FINISHED = "finished"
    EXITED = "exited"
    TIMED_OUT = "timed_out"


class RunnerProcess:
    """A runner the executor started (module docstring), keeping the memory limit it started
    with, which a warm runner cannot change."""

    def __init__(
        self,
        process: subprocess.Popen[str],
        end: Callable[[], None],
        memory_bytes: int,
        log: Path,
    ) -> None:
        self.process = process
        self.memory_bytes = memory_bytes
        self.log = log
        self._end = end
        self._stopping = threading.Lock()
        self._stopped = False
        self._log_start = 0
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._reader = threading.Thread(
            target=_queued_lines,
            args=(_piped(process.stdout), self._lines),
            name=f"lines of runner {process.pid}",
            daemon=True,
        )
        self._reader.start()

    def is_running(self) -> bool:
        return self.process.poll() is None

    def send(self, folder: Path) -> None:
        """Give the warm runner `folder`'s execution, whose log starts where the log ends now."""
        self._log_start = self.log.stat().st_size
        stdin = _piped(self.process.stdin)
        stdin.write(f"{folder}\n")
        stdin.flush()

    def relay(self, deadline: float, report: ProgressReport, check: StopCheck) -> RunnerEnd:
        """Give `report` each report of progress the runner prints, and ask `check` whenever
        `CHECK_SECONDS` pass without one, until the execution's result is in its folder, until
        the runner ends, or until `deadline`, an instant of `time.monotonic`; a line that is not
        a report is refused with a `RunnerOutputError`."""
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                line = self._lines.get(timeout=min(remaining, CHECK_SECONDS))
            except queue.Empty:
                check()
                continue
            if line is None:
                return RunnerEnd.EXITED
            if line == END_OF_EXECUTION:
                return RunnerEnd.FINISHED
            report(_progress(line))
        return RunnerEnd.TIMED_OUT

    def stop(self) -> int:
        """End the runner and every process it started, where they still run, from whichever
        thread asks first; its exit code."""
        with self._stopping:
            if not self._stopped:
                self._stopped = True
                self._end()
        return self.process.wait()

    def close(self) -> None:
        """Stop the runner, then let go of its pipes and remove its log."""
        self.stop()
        self._reader.join(READER_SECONDS)
        _closed_pipes(self.process)
        removed(self.log)

    def log_tail(self) -> str:
        """The end of the runner's log since its execution began: its stderr, and what the
        trader's code printed from C or Rust."""
        with self.log.open("rb") as log:
            log.seek(max(self._log_start, self.log.stat().st_size - LOG_TAIL_BYTES))
            return log.read().decode("utf-8", errors="replace")


def start_runner(paths: FefatPaths, memory_bytes: int, folder: Path | None) -> RunnerProcess:
    """A runner limited to `memory_bytes`, for `folder`'s execution, or warm without one, its
    working folder that execution's folder, so that a snippet's relative paths land there and go
    with it, or the executions' own."""
    command = [sys.executable, "-P", "-m", RUNNER_MODULE, "--memory-bytes", str(memory_bytes)]
    working_folder = paths.executions_dir
    if folder is not None:
        command.append(str(folder))
        working_folder = folder
    descriptor, log_name = tempfile.mkstemp(
        prefix="runner-", suffix=".log", dir=paths.executions_dir
    )
    environment = scrubbed_environment(paths, os.environ)
    try:
        with os.fdopen(descriptor, "wb") as log:
            process, end = _contained(command, environment, working_folder, log, memory_bytes)
    except BaseException:
        removed(Path(log_name))
        raise
    return RunnerProcess(process, end, memory_bytes, Path(log_name))


def _contained(
    command: list[str],
    environment: dict[str, str],
    working_folder: Path,
    log: BinaryIO,
    memory_bytes: int,
) -> tuple[subprocess.Popen[str], Callable[[], None]]:
    """The runner's process, started with its pipes, its log, and its environment, and what ends
    it with every process it starts (module docstring); a runner that cannot be contained is
    ended, and its pipes let go."""
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=log,
        cwd=working_folder,
        env=environment,
        encoding="utf-8",
        creationflags=CREATE_SUSPENDED if sys.platform == "win32" else 0,
        start_new_session=sys.platform != "win32",
    )
    if sys.platform != "win32":
        return process, partial(_end_session, process.pid)
    from fefat_app.executor.windows_job import JobObject

    try:
        job = JobObject.holding(process.pid, memory_bytes)
    except OSError:
        process.kill()
        _discarded(process)
        raise
    try:
        psutil.Process(process.pid).resume()
    except psutil.Error:
        job.close()
        _discarded(process)
        raise
    return process, job.close


def removed(path: Path) -> None:
    """Remove the file or folder `path`, trying again for `REMOVAL_SECONDS` while Windows still
    holds it, or a file in it, for a runner that has just ended; past them, it is logged and left
    in `cache/`, which may be deleted at any time, so that the cleaning never fails an execution
    that ended."""
    deadline = time.monotonic() + REMOVAL_SECONDS
    while True:
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
            return
        except OSError:
            if time.monotonic() > deadline:
                LOG.warning("The executor left %s, which another process still holds.", path)
                return
            time.sleep(0.01)


def leftovers_removed(folder: Path) -> None:
    """Remove each runner's log and execution's folder in `folder` that last changed more than
    `LEFT_SECONDS` ago, which Windows held past the removal or a server stopped during an
    execution left behind; the server's start calls it, before any runner of its own."""
    if not folder.is_dir():
        return
    oldest = time.time() - LEFT_SECONDS
    for path in folder.iterdir():
        if path.stat().st_mtime < oldest:
            removed(path)


def _progress(line: str) -> ExecutionProgress:
    """The report `line` holds; refused without the line's values, which may be prices (D-21)."""
    try:
        return ExecutionProgress.model_validate_json(line)
    except ValidationError as error:
        raise RunnerOutputError(
            f"Expected a report of progress from the runner, got: {problems(error)}."
        ) from error


def _end_session(session: int) -> None:
    """End every process of the runner's session `session`, the runner's pid, where they still
    run: elsewhere than on Windows, whose Job Object ends them."""
    if sys.platform != "win32":
        with contextlib.suppress(ProcessLookupError):
            os.killpg(session, signal.SIGKILL)


def _discarded(process: subprocess.Popen[str]) -> None:
    """Wait for a runner that could not be contained to end, then let go of its pipes."""
    process.wait()
    _closed_pipes(process)


def _closed_pipes(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdin, process.stdout):
        if stream is not None:
            with contextlib.suppress(OSError):
                stream.close()


def _queued_lines(stream: IO[str], lines: queue.Queue[str | None]) -> None:
    """Queue each line the runner prints, then None at the end of its output."""
    for line in stream:
        lines.put(line)
    lines.put(None)


def _piped[Stream](stream: Stream | None) -> Stream:
    if stream is None:
        raise ValueError(
            "Expected the runner's pipe, got none: start it with stdin and stdout piped."
        )
    return stream
