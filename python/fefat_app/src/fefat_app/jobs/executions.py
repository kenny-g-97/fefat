"""A job that runs an execution of the trader's code (step 4.5, `01-architecture.md` section 6): a
feature's preview or a snippet, its payload the spec of its kind, run by the worker's executor,
each report of the runner's progress a `progress` event of the job's stream, and the job's
request to stop read each second between them, so that the worker stops the runner itself rather
than the reaper ending the worker; an execution that ran out of time ends its job `timed_out`,
and one that failed ends it `failed` with the runner's error."""

from collections.abc import Mapping
from typing import Any

from fefat_app.execution import (
    ExecutionFailed,
    ExecutionTimedOut,
    FeaturePreviewSpec,
    PythonSnippetSpec,
)
from fefat_app.jobs.progress import JobProgress
from fefat_app.ports import Executor


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
    result = executor.run(
        spec,
        lambda reported: progress.advance(reported.percent, reported.message, **reported.details),
        progress.check,
    )
    if isinstance(result, ExecutionTimedOut):
        raise ExecutionTimedOutError(
            f"Expected the execution to end within {spec.limits.timeout_seconds:g} s, got it "
            "still running then: it was stopped."
        )
    if isinstance(result, ExecutionFailed):
        raise ExecutionFailedError(result.error)
    return result.model_dump(mode="json")
