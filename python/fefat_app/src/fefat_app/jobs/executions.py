"""A job that runs an execution of the trader's code (step 4.5, `01-architecture.md` section 6): a
feature's preview or a snippet, its payload the spec of its kind, run by the worker's executor,
each report of the runner's progress a `progress` event of the job's stream, and the job's
request to stop read each second between them, so that the worker stops the runner itself rather
than the reaper ending the worker; an execution that ran out of time ends its job `timed_out`,
and one that failed ends it `failed` with the runner's error. From step 5.3 a backtest's job runs
its execution through `executed` too (`fefat_app.jobs.backtests`), and from step 5.12 an
import's (`fefat_app.jobs.imports`)."""

from collections.abc import Mapping
from typing import Any

from fefat.market.calendar import counted
from fefat_app.execution import (
    BacktestSpec,
    ExecutionFailed,
    ExecutionSucceeded,
    ExecutionTimedOut,
    FeaturePreviewSpec,
    ProgressReport,
    PythonSnippetSpec,
    StopCheck,
)
from fefat_app.imports import ImportSpec
from fefat_app.jobs.progress import JobProgress
from fefat_app.ports import Executor

type JobSpec = FeaturePreviewSpec | PythonSnippetSpec | BacktestSpec | ImportSpec
"""The spec of an execution a job runs."""
NO_RESULT = (
    "The process running this job ended before it gave a result. Run it again, and if it ends "
    "the same way, read the log below."
)
"""What a job's error says first where its runner ended without a result (step 5.19)."""


class ExecutionTimedOutError(Exception):
    """The job's execution ran out of time and was stopped: the job ends `timed_out`."""


class ExecutionFailedError(Exception):
    """The job's execution failed: the job ends `failed` with the runner's error, its message."""


def run_execution(
    executor: Executor,
    kind: type[FeaturePreviewSpec] | type[PythonSnippetSpec],
    payload: Mapping[str, Any],
    progress: JobProgress,
) -> dict[str, Any]:
    """Run the execution of `payload`, a spec of `kind`, reporting through `progress`; its result,
    or the error the job ends with."""
    spec = kind.model_validate(payload)
    return executed(executor, spec, advancing(progress), progress.check).model_dump(mode="json")


def advancing(progress: JobProgress) -> ProgressReport:
    """Each report of the runner's progress as the job's (`JobProgress.advance`), which stops the
    execution where the job was asked to stop."""
    return lambda reported: progress.advance(reported.percent, reported.message, **reported.details)


def executed(
    executor: Executor, spec: JobSpec, report: ProgressReport, check: StopCheck
) -> ExecutionSucceeded:
    """The execution of `spec`, run to its end, its reports given to `report` and `check` asked
    each second without one; `ExecutionTimedOutError` or `ExecutionFailedError` where it did not
    end."""
    try:
        result = executor.run(spec, report, check)
    except OSError as refused:
        raise ExecutionFailedError(_cannot_start(spec, refused)) from refused
    if isinstance(result, ExecutionTimedOut):
        raise ExecutionTimedOutError(_past_its_limit(spec))
    if isinstance(result, ExecutionFailed):
        said = f"{NO_RESULT}\n\n{result.error}" if result.gave_no_result else result.error
        raise ExecutionFailedError(said)
    return result


def _cannot_start(spec: JobSpec, reason: OSError) -> str:
    """What a job's error says where its runner could not start; an import's names its file,
    since a round goes on with the others."""
    if isinstance(spec, ImportSpec):
        return (
            "This file's import could not start its process. Free some disk space or "
            f"memory and import it again: {reason}"
        )
    return (
        "This job could not start its process. Free some disk space or memory and run it "
        f"again: {reason}"
    )


def _past_its_limit(spec: JobSpec) -> str:
    """What a job's error says where it ran out of time; an import's leaves what to do to
    `fefat_app.jobs.imports`, since that depends on whether it wrote."""
    limit = _duration(spec.limits.timeout_seconds)
    if isinstance(spec, ImportSpec):
        return f"This file's import ran past its limit of {limit} and was stopped."
    return (
        f"This job ran past its limit of {limit} and was stopped. Run again repeats the same "
        "data, so start a new one on less data."
    )


def _duration(seconds: float) -> str:
    """`seconds` as a person says it: `6 hours`, `30 minutes`, `2 seconds`."""
    for size, unit in ((3600, "hour"), (60, "minute")):
        if seconds >= size and seconds % size == 0:
            return counted(int(seconds // size), unit)
    return f"{seconds:g} seconds"
