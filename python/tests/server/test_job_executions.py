"""The executions of step 4.5 as jobs (`01-architecture.md` section 6): a worker runs a snippet's or
a preview's job through an executor of its own, each report of the runner a `progress` event of
the job's stream; a snippet that runs out of time ends its job `timed_out` (`BACKLOG.md`), one
asked to stop ends `cancelled` within a second or two, its worker stopping the runner, one that
runs to its end succeeds with what it printed, and a preview whose code defines no feature fails
with the runner's error; run in this process, as `test_job_worker` runs the worker."""

import os
import threading
import time
from datetime import UTC, datetime

import pytest

from fefat.config import resolve_paths
from fefat_app.database.job_records import JobTables
from fefat_app.execution import (
    ExecutionLimits,
    ExecutionResult,
    ExecutionSpec,
    ProgressReport,
    PythonSnippetSpec,
    StopCheck,
    keep_running,
)
from fefat_app.job_models import Job, JobKind, JobStatus, job_stream
from fefat_app.jobs.executions import ExecutionFailedError, executed
from fefat_app.jobs.worker import JobTimings, run_job
from local_server import STARTED_AT, running_runners

GIB = 1024**3
DEADLINE_SECONDS = 60


def ran(job_records: JobTables, kind: JobKind, payload: dict[str, object]) -> Job:
    """The job of `kind` with `payload`, queued, then run by a worker in this process."""
    job = job_records.add(kind, payload, 3, STARTED_AT)
    run_job(job.id, resolve_paths(os.environ), JobTimings())
    ended = job_records.by_id(job.id)
    assert ended is not None
    return ended


def snippet(code: str, timeout_seconds: float = 60) -> dict[str, object]:
    limits = ExecutionLimits(timeout_seconds=timeout_seconds, memory_bytes=8 * GIB)
    return PythonSnippetSpec(code=code, bars=None, limits=limits).model_dump(mode="json")


def test_a_snippet_job_that_runs_out_of_time_ends_timed_out_after_its_progress(
    job_records: JobTables,
) -> None:
    # The runner's line of progress reaches the job's stream, and its timeout the job's status.
    ended = ran(job_records, JobKind.PYTHON_SNIPPET, snippet("import time\ntime.sleep(60)\n", 2))

    assert (ended.status, ended.result) == (JobStatus.TIMED_OUT, None)
    assert ended.error == (
        "This job ran past its limit of 2 seconds and was stopped. Run again repeats the "
        "same data, so start a new one on less data."
    )
    events = job_records.events_after(job_stream(ended.id), 0, 100)
    assert [(event.event_type, event.said) for event in events] == [
        ("status", {"status": "queued"}),
        ("status", {"status": "running"}),
        ("progress", {"percent": 30.0, "message": "Running the snippet", "details": {}}),
        ("status", {"status": "timed_out"}),
    ]
    assert running_runners() == []


def test_a_snippet_job_asked_to_stop_ends_cancelled_by_its_worker(job_records: JobTables) -> None:
    # The snippet reports nothing while it runs, so the worker asks each second whether its job
    # runs on and stops the runner itself, where the reaper, which this test has none of, would
    # end the pool's worker ten seconds later (step 4.4).
    job = job_records.add(
        JobKind.PYTHON_SNIPPET, snippet("import time\ntime.sleep(60)\n"), 3, STARTED_AT
    )
    worker = threading.Thread(
        target=run_job, args=(job.id, resolve_paths(os.environ), JobTimings())
    )
    worker.start()
    deadline = time.monotonic() + DEADLINE_SECONDS
    while _progress_of(job_records, job.id) < 30:
        assert time.monotonic() < deadline, (
            f"Expected the snippet to run within {DEADLINE_SECONDS} s."
        )
        time.sleep(0.05)

    job_records.request_cancel(job.id, datetime.now(UTC))
    began = time.monotonic()
    worker.join(DEADLINE_SECONDS)

    ended = job_records.by_id(job.id)
    assert ended is not None
    assert ended.status == JobStatus.CANCELLED
    assert time.monotonic() - began < 5
    assert running_runners() == []


def _progress_of(job_records: JobTables, job_id: str) -> float:
    now = job_records.by_id(job_id)
    assert now is not None
    return now.progress


def test_a_snippet_job_succeeds_with_what_it_printed(job_records: JobTables) -> None:
    ended = ran(job_records, JobKind.PYTHON_SNIPPET, snippet("print(6 * 7)\n"))

    assert (ended.status, ended.error) == (JobStatus.SUCCEEDED, None)
    assert ended.result == {
        "outcome": "succeeded",
        "output": {"kind": "python_snippet", "stdout_tail": "42\n"},
    }


def test_a_preview_job_whose_code_defines_no_feature_fails_with_the_runner_s_error(
    job_records: JobTables,
) -> None:
    payload = {
        "code": "threshold = 3\n",
        "parameters": {},
        "bars": {"instrument": "ES", "timeframe": "5m", "start": "2026-02-02", "end": "2026-02-27"},
        "limits": {"timeout_seconds": 60, "memory_bytes": 8 * GIB},
    }

    ended = ran(job_records, JobKind.FEATURE_PREVIEW, payload)

    assert ended.status == JobStatus.FAILED
    assert ended.error is not None
    assert ended.error.startswith("Traceback (most recent call last):")
    assert ended.error.endswith(
        "ValueError: Expected the code of one feature, a function under its @ff.feature(...) "
        "call, got 1 statement.\n"
    )


def test_a_job_whose_runner_ends_without_a_result_says_what_to_do_above_its_log(
    job_records: JobTables,
) -> None:
    # Step 5.19: what the executor writes for a developer stays, with its line breaks, under a
    # sentence in the trader's words.
    code = "import os, sys\nprint('from the runner', file=sys.stderr, flush=True)\nos._exit(3)\n"

    ended = ran(job_records, JobKind.PYTHON_SNIPPET, snippet(code))

    assert ended.status == JobStatus.FAILED
    assert ended.error is not None
    first, blank, *details = ended.error.split("\n")
    assert first == (
        "The process running this job ended before it gave a result. Run it again, and if it "
        "ends the same way, read the log below."
    )
    assert blank == ""
    assert "The runner ended with exit code" in details[0]
    assert any(line.startswith("from the runner") for line in details[1:])


def test_a_job_whose_payload_is_of_another_kind_fails_before_any_runner_starts(
    job_records: JobTables,
) -> None:
    ended = ran(job_records, JobKind.FEATURE_PREVIEW, snippet("print(1)\n"))

    assert ended.status == JobStatus.FAILED
    assert ended.error is not None
    assert ended.error.startswith("ValidationError: ")


class CannotStart:
    """An executor whose runner cannot start, as on a full disk."""

    def run(
        self, spec: ExecutionSpec, report: ProgressReport, check: StopCheck = keep_running
    ) -> ExecutionResult:
        raise OSError(28, "No space left on device")

    def close(self) -> None:
        """Nothing to end."""


def test_a_job_whose_runner_cannot_start_says_what_to_do() -> None:
    spec = PythonSnippetSpec.model_validate(snippet("print(1)\n"))

    with pytest.raises(ExecutionFailedError) as failed:
        executed(CannotStart(), spec, lambda _: None, keep_running)

    said = str(failed.value)
    assert said.startswith(
        "This job could not start its process. Free some disk space or memory and run it again: "
    )
    assert said.endswith("No space left on device")
