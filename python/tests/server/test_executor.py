"""The executor of step 4.5 (`01-architecture.md` section 6) on snippets, each run by a runner of
its own: a snippet that loops for ever is stopped at its timeout, and one that allocates past its
memory limit fails there, neither reaching the test's process; a snippet sees no secret of the
environment, and keyring gives it none; a result the runner left that is not one is refused; and
a snippet reads its bars and gives back the tail of what it printed (Done means 1). They run on
Windows here and on Linux in CI, whose limits differ: a Job Object's commit charge on Windows, the
address space (`RLIMIT_AS`) on Linux."""

import ast
import re
import time
from datetime import date
from pathlib import Path

import polars as pl
import pytest

from fefat.config import FefatPaths
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
from fefat_app.executor.environment import scrubbed_environment
from fefat_app.executor.protocol import (
    RESULT_BYTES,
    RESULT_FILE,
    SERIES_FILE,
    SERIES_POINTS,
    SERIES_SCHEMA,
    read_result_file,
    read_series,
)
from fefat_app.executor.snippet import TAIL_CHARS
from fefat_app.executor.subprocess_executor import SubprocessExecutor
from generated_minutes import FEBRUARY, write_minutes
from local_server import running_runners

GIB = 1024**3
MIB = 1024**2
ROOMY = ExecutionLimits(timeout_seconds=60, memory_bytes=8 * GIB)
"""Limits no test snippet but the ones testing them comes near."""


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


def test_a_snippet_that_raises_fails_with_its_traceback_and_what_it_printed(
    executor: SubprocessExecutor,
) -> None:
    result, _ = ran(executor, "print('before')\nraise ValueError('planted')\n")

    assert isinstance(result, ExecutionFailed), result
    assert result.error.endswith("ValueError: planted\n")
    assert 'File "<snippet>", line 2' in result.error
    assert result.stdout_tail == "before\n"


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
        "FEFAT_HOME": "/elsewhere",
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
