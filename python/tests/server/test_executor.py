"""The executor of step 4.5 (`01-architecture.md` section 6) on snippets, each run by a runner of
its own: a snippet that loops for ever is stopped at its timeout, with the processes it started,
and one that allocates past its memory limit fails there, neither reaching the test's process; no
runner outlives the process of its executor; a snippet sees no secret of the environment, and
keyring gives it none; a result the runner left that is not one is refused; and a snippet reads
its bars and gives back the tail of what it printed (Done means 1). They run on Windows here and
on Linux in CI, whose limits differ: a Job Object's commit charge on Windows, the address space
(`RLIMIT_AS`) on Linux."""

import ast
import os
import re
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path

import polars as pl
import psutil
import pytest
from pydantic import ValidationError

from fefat.config import DATA_DIR_VARIABLE, HOME_VARIABLE, FefatPaths, resolve_paths
from fefat.market.api import SIGNAL_BAR_COLUMNS
from fefat_app.execution import (
    BarsReference,
    ExecutionFailed,
    ExecutionLimits,
    ExecutionProgress,
    ExecutionResult,
    ExecutionSucceeded,
    ExecutionTimedOut,
    PythonSnippetOutput,
    PythonSnippetSpec,
)
from fefat_app.executor import runner_process
from fefat_app.executor.environment import scrubbed_environment
from fefat_app.executor.protocol import (
    RESULT_BYTES,
    RESULT_FILE,
    SERIES_FILE,
    SERIES_POINTS,
    SERIES_SCHEMA,
    RunnerOutputError,
    read_result_file,
    read_series,
)
from fefat_app.executor.runner_process import removed
from fefat_app.executor.snippet import TAIL_CHARS
from fefat_app.executor.subprocess_executor import SubprocessExecutor
from generated_minutes import FEBRUARY, write_minutes
from local_server import running_runners

GIB = 1024**3
MIB = 1024**2
ROOMY = ExecutionLimits(timeout_seconds=60, memory_bytes=8 * GIB)
"""Limits no test snippet but the ones testing them comes near."""
DEADLINE_SECONDS = 60
SPAWNS = """\
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
started = [psutil.Process(pid) for pid in (os.getpid(), child.pid)]
Path({started!r} + ".tmp").write_text(repr([(each.pid, each.create_time()) for each in started]))
os.replace({started!r} + ".tmp", {started!r})
while True:
    time.sleep(0.1)
"""
"""A snippet that starts a process that sleeps for ten minutes, writes its own process's and that
process's pids and start times to the file `started`, then sleeps for ever."""


def ran(
    executor: SubprocessExecutor,
    code: str,
    limits: ExecutionLimits = ROOMY,
    bars: BarsReference | None = None,
) -> tuple[ExecutionResult, list[ExecutionProgress]]:
    """How the snippet `code` ended, and the progress it reported, in order."""
    reports: list[ExecutionProgress] = []
    result = executor.run(PythonSnippetSpec(code=code, bars=bars, limits=limits), reports.append)
    return result, reports


def printed(result: ExecutionResult) -> str:
    """The tail of what a snippet that ran to its end printed."""
    assert isinstance(result, ExecutionSucceeded), result
    assert isinstance(result.output, PythonSnippetOutput)
    return result.output.stdout_tail


def started_by(snippet: Path) -> list[tuple[int, float]]:
    """The processes that `SPAWNS` wrote to `snippet`, waited for: the runner's interpreter and
    the process it started, each by its pid and start time."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    while not snippet.exists():
        assert time.monotonic() < deadline, f"Expected {snippet.name} within {DEADLINE_SECONDS} s."
        time.sleep(0.1)
    return ast.literal_eval(snippet.read_text())


def ended(processes: list[tuple[int, float]]) -> bool:
    """Whether none of `processes` runs, a process of the same pid started since being another."""
    for pid, started in processes:
        try:
            process = psutil.Process(pid)
            if process.create_time() == started and process.status() != psutil.STATUS_ZOMBIE:
                return False
        except psutil.NoSuchProcess:
            continue
    return True


def waited_until_ended(processes: list[tuple[int, float]]) -> None:
    deadline = time.monotonic() + 10
    while not ended(processes):
        assert time.monotonic() < deadline, f"Expected {processes} to end within 10 s."
        time.sleep(0.1)


def test_a_snippet_that_loops_for_ever_is_stopped_at_its_timeout(
    executor: SubprocessExecutor,
) -> None:
    # Done means 1: the runner is ended at the wall clock's limit, and nothing of it runs on.
    limits = ExecutionLimits(timeout_seconds=3, memory_bytes=8 * GIB)
    began = time.monotonic()

    result, _ = ran(executor, "while True:\n    pass\n", limits)

    took = time.monotonic() - began
    print(f"stopped after {took:.2f} s")
    assert result == ExecutionTimedOut()
    assert 3 <= took < 15
    assert running_runners() == []


def test_a_snippet_stopped_at_its_timeout_takes_the_processes_it_started_with_it(
    executor: SubprocessExecutor, tmp_path: Path
) -> None:
    # The Job Object on Windows, and the runner's session elsewhere, end a process the trader's
    # code started with the runner.
    snippet = tmp_path / "started.txt"
    limits = ExecutionLimits(timeout_seconds=8, memory_bytes=8 * GIB)

    result, _ = ran(executor, SPAWNS.format(started=str(snippet)), limits)

    assert result == ExecutionTimedOut()
    waited_until_ended(started_by(snippet))


PARENT = """\
import os
from pathlib import Path

from fefat.config import resolve_paths
from fefat_app.execution import ExecutionLimits, PythonSnippetSpec
from fefat_app.executor.subprocess_executor import SubprocessExecutor

Path({parent!r}).write_text(str(os.getpid()))
limits = ExecutionLimits(timeout_seconds=600, memory_bytes=8 * 1024**3)
spec = PythonSnippetSpec(code={code!r}, bars=None, limits=limits)
SubprocessExecutor(resolve_paths(os.environ), warm_previews=False).run(spec, lambda progress: None)
"""
"""A process that runs the snippet `code` with a ten-minute timeout, having written its pid to
the file `parent`."""


def test_no_runner_outlives_the_process_of_its_executor(tmp_path: Path) -> None:
    # A worker the reaper ends, or a server that crashes, takes its runners with it: on Windows
    # its handle to their Job Object closes, and elsewhere their stdin ends, whose reader ends
    # the runner's session.
    snippet, parent_pid = tmp_path / "started.txt", tmp_path / "parent.txt"
    script = tmp_path / "parent.py"
    code = SPAWNS.format(started=str(snippet))
    script.write_text(PARENT.format(parent=str(parent_pid), code=code), encoding="utf-8")
    parent = subprocess.Popen([sys.executable, str(script)], env=os.environ)
    try:
        started = started_by(snippet)
        psutil.Process(int(parent_pid.read_text())).kill()

        waited_until_ended(started)
    finally:
        parent.kill()
        parent.wait(DEADLINE_SECONDS)


PEAK_MEMORY = """\
import sys

if sys.platform == "win32":
    import psutil

    print(psutil.Process().memory_info().peak_pagefile)
else:
    with open("/proc/self/status") as status:
        print(next(int(line.split()[1]) * 1024 for line in status if line.startswith("VmPeak:")))
"""
"""What the limit counts that a runner took at most by the time it ran a snippet: its commit
charge on Windows, its address space on Linux."""
BOMB = """\
blocks = []
for count in range(1, 17):
    blocks.append(bytearray(64 * 1024 * 1024))
    print(count)
"""
"""A snippet that would hold a GiB, 64 MiB at a time, printing how many blocks it holds."""


def test_a_snippet_that_allocates_past_its_memory_limit_fails_there(
    executor: SubprocessExecutor,
) -> None:
    # Done means 1, sized small: the limit is a quarter of a GiB above what a runner took to start,
    # measured first, so that the same test holds where the limit counts the address space; the
    # snippet's MemoryError fails the execution after a few blocks, and the test's process never
    # sees the memory.
    started_with = int(printed(ran(executor, PEAK_MEMORY)[0]))
    limits = ExecutionLimits(timeout_seconds=60, memory_bytes=started_with + 256 * MIB)

    result, _ = ran(executor, BOMB, limits)

    assert isinstance(result, ExecutionFailed), result
    assert "MemoryError" in result.error
    held = [int(count) for count in result.stdout_tail.split()]
    print(f"a runner took {started_with / MIB:.0f} MiB; the snippet held {held[-1:]} blocks")
    assert 1 <= len(held) < 16
    assert running_runners() == []


PLANTED_SECRETS = {
    "ANTHROPIC_API_KEY": "planted-by-the-test",
    "DATABENTO_API_KEY": "planted-by-the-test",
    "AWS_SECRET_ACCESS_KEY": "planted-by-the-test",
    "DATABASE_URL": "planted-by-the-test",
}
WHAT_IT_SEES = """\
import os

import keyring

print(sorted(os.environ))
print(type(keyring.get_keyring()).__module__)
print(keyring.get_password("fefat", "anthropic"))
"""


def test_a_snippet_sees_no_secret_of_the_environment_and_keyring_gives_it_none(
    executor: SubprocessExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Done means 1: the runner's environment keeps the system's variables and FEFAT's folders
    # alone, and keyring's null backend, which keeps nothing, answers a snippet asking for a key.
    for name, value in PLANTED_SECRETS.items():
        monkeypatch.setenv(name, value)

    names, backend, anthropic = printed(ran(executor, WHAT_IT_SEES)[0]).splitlines()

    seen = set(ast.literal_eval(names))
    assert not seen & set(PLANTED_SECRETS)
    assert {"FEFAT_HOME", "FEFAT_DATA_DIR", "PYTHON_KEYRING_BACKEND"} <= seen
    assert (backend, anthropic) == ("keyring.backends.null", "None")


FORGES_ITS_RESULT = """\
import os
from pathlib import Path

Path("result.json").write_text('{"outcome": "succeeded", "output": {"kind": "python_snippet"}}')
os._exit(0)
"""
"""A snippet that leaves a result without its stdout tail in its folder, the runner's working
folder, and ends the runner before the runner writes its own."""


def test_a_result_the_runner_left_that_is_not_a_result_is_refused(
    executor: SubprocessExecutor,
) -> None:
    # Done means 1: the result is validated before it is trusted.
    result, _ = ran(executor, FORGES_ITS_RESULT)

    assert isinstance(result, ExecutionFailed), result
    assert result.error.startswith("Expected result.json to hold the result of an execution")
    assert "stdout_tail" in result.error


def test_a_result_file_past_its_size_is_refused_unread(tmp_path: Path) -> None:
    # Done means 1: what the runner leaves is capped before it is read into the server.
    (tmp_path / RESULT_FILE).write_bytes(b" " * (RESULT_BYTES + 1))

    expected = f"Expected {RESULT_FILE} of at most {RESULT_BYTES} bytes, got more."
    with pytest.raises(ValueError, match=re.escape(expected)):
        read_result_file(tmp_path)


def test_a_series_file_that_is_not_one_is_refused(tmp_path: Path) -> None:
    # Done means 1: a preview's Parquet output is checked for its schema, its points, and its
    # values before it is trusted.
    series = tmp_path / SERIES_FILE
    pl.DataFrame({"output": ["rsi"], "ts_close": [1], "price": [1.0]}).write_parquet(series)
    with pytest.raises(ValueError, match=re.escape("Expected series.parquet of the columns")):
        read_series(tmp_path)
    many = SERIES_POINTS + 1
    points = {"output": ["rsi"] * many, "ts_close": range(many), "value": [1.0] * many}
    pl.DataFrame(points, schema=SERIES_SCHEMA).write_parquet(series)
    with pytest.raises(ValueError, match=f"Expected at most {SERIES_POINTS} points an output"):
        read_series(tmp_path)
    nan = {"output": ["rsi"], "ts_close": [1], "value": [float("nan")]}
    pl.DataFrame(nan, schema=SERIES_SCHEMA).write_parquet(series)
    with pytest.raises(ValueError, match=re.escape("Expected series.parquet to hold points")):
        read_series(tmp_path)
    series.write_bytes(b"not Parquet")
    with pytest.raises(ValueError, match=re.escape("Expected series.parquet to be Parquet")):
        read_series(tmp_path)


def test_a_snippet_reads_its_bars_and_gives_back_the_tail_of_what_it_printed(
    executor: SubprocessExecutor,
) -> None:
    write_minutes(FEBRUARY)
    week = BarsReference(
        instrument="ES", timeframe="5m", start=date(2026, 2, 9), end=date(2026, 2, 13)
    )
    code = "for line in range(10_000):\n    print(line)\nprint(bars.collect_schema().names())\n"

    result, reports = ran(executor, code, bars=week)

    tail = printed(result).splitlines()
    assert tail[-1] == str(SIGNAL_BAR_COLUMNS.names())
    assert tail[-2] == "9999"
    assert len(printed(result)) <= TAIL_CHARS
    assert [(report.percent, report.message) for report in reports] == [
        (20, "Loaded the bars of ES at 5m from 2026-02-09 to 2026-02-13"),
        (30, "Running the snippet"),
    ]


def test_a_snippet_that_ends_with_sys_exit_succeeds_or_fails_by_its_status(
    executor: SubprocessExecutor,
) -> None:
    ended_well, _ = ran(executor, "import sys\nprint('done')\nsys.exit(0)\n")
    ended_badly, _ = ran(executor, "import sys\nprint('half')\nsys.exit(3)\n")

    assert printed(ended_well) == "done\n"
    assert isinstance(ended_badly, ExecutionFailed), ended_badly
    assert ended_badly.error.endswith("SystemExit: 3\n")
    assert ended_badly.stdout_tail == "half\n"


def test_a_line_of_the_runner_that_is_not_a_report_is_refused_without_its_values() -> None:
    # A runner that dies in the middle of a line fails its execution rather than raising past it,
    # and the refusal quotes no value, which may be a price (D-21).
    with pytest.raises(RunnerOutputError, match="Expected a report of progress") as refused:
        runner_process._progress('{"percent": 4512.25, "message": "Computed"}\n')

    assert "4512.25" not in str(refused.value)


def test_limits_past_a_day_or_what_64_bits_hold_are_refused() -> None:
    with pytest.raises(ValidationError, match="timeout_seconds"):
        ExecutionLimits(timeout_seconds=float("inf"), memory_bytes=GIB)
    with pytest.raises(ValidationError, match="memory_bytes"):
        ExecutionLimits(timeout_seconds=5, memory_bytes=2**64)


def test_a_snippet_that_raises_fails_with_its_traceback_and_what_it_printed(
    executor: SubprocessExecutor,
) -> None:
    result, _ = ran(executor, "print('before')\nraise ValueError('planted')\n")

    assert isinstance(result, ExecutionFailed), result
    assert result.error.endswith("ValueError: planted\n")
    assert 'File "<snippet>", line 2' in result.error
    assert result.stdout_tail == "before\n"


def test_what_a_runner_still_holds_is_removed_once_it_lets_go(tmp_path: Path) -> None:
    # Windows refuses to remove a file another handle holds, as it holds a stopped runner's log
    # and working folder for some milliseconds after the runner has gone.
    log = tmp_path / "runner.log"
    folder = tmp_path / "execution"
    folder.mkdir()
    held = [log.open("wb"), (folder / "result.json").open("wb")]
    threading.Timer(0.2, lambda: [handle.close() for handle in held]).start()

    removed(log)
    removed(folder)

    assert sorted(tmp_path.iterdir()) == []


def test_a_runner_that_fails_to_start_leaves_no_log(
    executor: SubprocessExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*arguments: object) -> None:
        raise OSError("planted: no runner today")

    monkeypatch.setattr(runner_process, "_contained", refused)

    with pytest.raises(OSError, match="planted"):
        ran(executor, "print(1)\n")
    # The executor fixture checks that its folder holds nothing, neither the log nor the folder.


def test_the_runner_s_environment_keeps_the_system_s_variables_and_fefat_s_folders_alone(
    tmp_path: Path,
) -> None:
    paths = FefatPaths(home=tmp_path / "home", data_dir=tmp_path / "data")
    given = {
        "Path": "/bin",
        "SYSTEMROOT": "C:/Windows",
        "TEMP": "/tmp",
        "HOME": "/home/trader",
        "PYTHONPATH": "/src",
        "ANTHROPIC_API_KEY": "planted-by-the-test",
        "GITHUB_TOKEN": "planted-by-the-test",
        "DATABASE_URL": "planted-by-the-test",
        "HTTPS_PROXY": "planted-by-the-test",
        "FEFAT_HOME": str(tmp_path / "elsewhere"),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.fail.Keyring",
    }

    assert scrubbed_environment(paths, given) == {
        "Path": "/bin",
        "SYSTEMROOT": "C:/Windows",
        "TEMP": "/tmp",
        "HOME": "/home/trader",
        "PYTHONPATH": "/src",
        "FEFAT_HOME": str(paths.home),
        "FEFAT_DATA_DIR": str(paths.data_dir),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
        "PYTHONUTF8": "1",
    }


def test_a_runner_of_a_server_on_the_default_home_resolves_it_as_the_server_did() -> None:
    # A git working tree around the user's folders, as a dotfiles repository makes, refuses a
    # FEFAT_HOME only where the environment sets it (D-85): a server on the platform's default
    # home gives its runners none, so that they resolve that home, unchecked, as it did.
    paths = resolve_paths({})

    scrubbed = scrubbed_environment(paths, {"PATH": "/bin"})

    assert HOME_VARIABLE not in scrubbed
    assert DATA_DIR_VARIABLE not in scrubbed
