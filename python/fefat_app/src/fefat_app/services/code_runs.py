"""The trader's code run in the executor for the library (step 5.2, D-91, D-93): a strategy's code
validated, a strategy version saved, and a feature version saved, each in a runner of its own
within `LIBRARY_LIMITS`, never in the server; an execution that ran out of time or failed is a
refusal without a line, in words of its own. From step 5.3 a saved version's run is looked up
alike, and a backtest's job runs within `BACKTEST_LIMITS`."""

from fefat_app.execution import (
    ExecutionFailed,
    ExecutionLimits,
    ExecutionProgress,
    ExecutionTimedOut,
    FeatureSaveOutput,
    FeatureSaveSpec,
    LibraryOutput,
    LibrarySpec,
    RefusedCode,
    RunLookupOutput,
    RunLookupSpec,
    SavedVersion,
    StrategySaveOutput,
    StrategySaveSpec,
    StrategyValidationOutput,
    StrategyValidationSpec,
    ValidStrategy,
)
from fefat_app.ports import Executor
from fefat_app.runs import RequestedRun, RunToMake, SavedRunFound

LIBRARY_LIMITS = ExecutionLimits(timeout_seconds=60, memory_bytes=4 * 1024**3)
"""What a validation, a save, or a run's lookup may take: a minute and 4 GiB, far more than
building a strategy on bars with no rows, or looking up its run, takes."""
BACKTEST_LIMITS = ExecutionLimits(timeout_seconds=6 * 60 * 60, memory_bytes=8 * 1024**3)
"""What a backtest's job may take: six hours and 8 GiB (your answer at step 5.3's plan)."""


class CodeRefusedError(ValueError):
    """Code the SDK refused, or whose execution ran out of time or failed, with the line of the
    code the refusal is at, None where it has none."""

    def __init__(self, refusal: RefusedCode) -> None:
        super().__init__(refusal.message)
        self.line = refusal.line


def validated(executor: Executor, code: str) -> ValidStrategy | RefusedCode:
    """A strategy's code built in a runner as a version's is, valid or refused."""
    spec = StrategyValidationSpec(code=code, limits=LIBRARY_LIMITS)
    output = _output(executor, spec, StrategyValidationOutput)
    return output if isinstance(output, RefusedCode) else output.answer


def saved_strategy(executor: Executor, spec: StrategySaveSpec) -> SavedVersion:
    """The strategy version `spec` saves in a runner; refused with `CodeRefusedError`."""
    output = _output(executor, spec, StrategySaveOutput)
    return _saved(output if isinstance(output, RefusedCode) else output.answer)


def saved_feature(executor: Executor, spec: FeatureSaveSpec) -> SavedVersion:
    """The feature version `spec` saves in a runner; refused with `CodeRefusedError`."""
    output = _output(executor, spec, FeatureSaveOutput)
    return _saved(output if isinstance(output, RefusedCode) else output.answer)


def looked_up_run(executor: Executor, run: RequestedRun) -> SavedRunFound | RunToMake:
    """What the lookup of `run` in a runner finds; refused with `CodeRefusedError`."""
    output = _output(executor, RunLookupSpec(run=run, limits=LIBRARY_LIMITS), RunLookupOutput)
    answer = output if isinstance(output, RefusedCode) else output.answer
    if isinstance(answer, RefusedCode):
        raise CodeRefusedError(answer)
    return answer


def _saved(answer: SavedVersion | RefusedCode) -> SavedVersion:
    if isinstance(answer, RefusedCode):
        raise CodeRefusedError(answer)
    return answer


def _output[Output: LibraryOutput | RunLookupOutput](
    executor: Executor, spec: LibrarySpec | RunLookupSpec, output_type: type[Output]
) -> Output | RefusedCode:
    """What the execution of `spec` gave, of `output_type`, or the refusal of an execution that
    ran out of time or failed."""
    result = executor.run(spec, _unreported)
    if isinstance(result, ExecutionTimedOut):
        return RefusedCode(
            line=None,
            message=f"Expected the code to end within {spec.limits.timeout_seconds:g} s, got it "
            "still running then: it was stopped.",
        )
    if isinstance(result, ExecutionFailed):
        return RefusedCode(line=None, message=result.error)
    output = result.output
    if not isinstance(output, output_type):
        raise ValueError(f"Expected the output of a {spec.kind}, got that of a {output.kind}.")
    return output


def _unreported(progress: ExecutionProgress) -> None:
    """The library's executions report nothing their callers show."""
