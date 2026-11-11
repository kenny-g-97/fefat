"""A saved strategy version's lookup and its backtest in the runner (step 5.3, D-91, D-93): the
strategy is built from the version's code with its parameters (`StrategyVersion.strategy`), here,
never in the server; the lookup answers what `fefat.backtest.requests.looked_up` finds, the code's
refusal coming back as its answer, with its line where it has one, as the library's executions
answer (`fefat_app.executor.versions`); and the backtest runs `ff.backtest.run`, reporting each of
its stages, and answers its run key, what it raises failing the execution."""

import os
from collections.abc import Callable

from pydantic import JsonValue, ValidationError

import fefat as ff
from fefat.backtest import RunStage
from fefat.backtest.requests import looked_up
from fefat.config import resolve_paths
from fefat.strategy import SignalStrategy, StrategyCodeError, StrategyVersion
from fefat_app.execution import (
    BacktestOutput,
    BacktestSpec,
    ExecutionProgress,
    ProgressReport,
    RefusedCode,
    RunLookupOutput,
    RunLookupSpec,
)
from fefat_app.executor.protocol import ERROR_CHARS, problems
from fefat_app.runs import RequestedRun, RunToMake, SavedRunFound

STAGES = {
    RunStage.DATA_LOADED: (30.0, "Loaded the data"),
    RunStage.FEATURES_COMPUTED: (50.0, "Computed the features and signals"),
    RunStage.ENGINE_RUNNING: (60.0, "Running the engine"),
    RunStage.ARTIFACTS_WRITTEN: (100.0, "Wrote the artifacts"),
}
"""The percent and the message of each stage a backtest tells (`RunStage`): the engine's run is one
call of the binding, so its percent is the stage's start and end."""
OPENED = ExecutionProgress(percent=100.0, message="Opened the saved run", details={})
"""The report of a backtest that found its run saved, which wrote nothing."""


def run_lookup_output(spec: RunLookupSpec) -> RunLookupOutput:
    """What the lookup of `spec`'s run finds, or the refusal of what the SDK refused."""
    try:
        return RunLookupOutput(answer=_looked_up(spec.run))
    except StrategyCodeError as refused:
        return RunLookupOutput(answer=_refused(str(refused), refused.line))
    except ValidationError as refused:
        return RunLookupOutput(answer=_refused(problems(refused), None))
    except (ValueError, OSError) as refused:
        return RunLookupOutput(answer=_refused(str(refused), None))


def backtest_output(spec: BacktestSpec, report: ProgressReport) -> BacktestOutput:
    """The run of `spec`'s backtest, each stage reported as it comes; a run found saved reports
    that it was opened."""
    told: list[RunStage] = []
    run = ff.backtest.run(
        _strategy(spec.run),
        spec.run.start,
        spec.run.end,
        spec.run.settings,
        progress=_reporting(report, told),
    )
    if RunStage.ARTIFACTS_WRITTEN not in told:
        report(OPENED)
    return BacktestOutput(run_key=run.hash)


def _looked_up(run: RequestedRun) -> SavedRunFound | RunToMake:
    strategy = _strategy(run)
    lookup = looked_up(strategy, run.start, run.end, run.settings, resolve_paths(os.environ))
    pin = strategy.saved_version
    parameters: dict[str, JsonValue] = {} if pin is None else dict(pin.parameters)
    if lookup.request is None:
        return RunToMake(request_key=None, parameters=parameters, settings=lookup.config)
    request_key = lookup.request.key()
    if lookup.saved is None:
        return RunToMake(request_key=request_key, parameters=parameters, settings=lookup.config)
    return SavedRunFound(
        run_key=lookup.saved.name,
        request_key=request_key,
        parameters=parameters,
        settings=lookup.config,
    )


def _strategy(run: RequestedRun) -> SignalStrategy:
    """The strategy the version `run` names gives with its parameters, refused where the
    version's file is not the one the index holds."""
    return _version(run).strategy(**run.parameters)


def _version(run: RequestedRun) -> StrategyVersion:
    version = ff.strategy.load(run.strategy, run.version)
    if version.hash != run.hash:
        raise ValueError(
            f"Expected version {run.version} of strategy {run.strategy} with the hash "
            f"{run.hash[:12]} as indexed, got {version.hash[:12]}: its file was replaced after it "
            "was indexed."
        )
    return version


def _reporting(report: ProgressReport, told: list[RunStage]) -> Callable[[RunStage], None]:
    """What a run tells of its stages, reported as the execution's progress, and kept in
    `told`."""

    def tell(stage: RunStage) -> None:
        told.append(stage)
        percent, message = STAGES[stage]
        report(ExecutionProgress(percent=percent, message=message, details={}))

    return tell


def _refused(message: str, line: int | None) -> RefusedCode:
    return RefusedCode(line=line, message=message[:ERROR_CHARS])
