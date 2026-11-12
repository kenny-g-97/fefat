"""A saved version's lookup and its backtest in the executor (step 5.3, D-91, D-93): the strategy is
built from its version's code in a runner of its own, never in the server; the lookup answers the
parameters as bound and the settings as applied, with the run key of the saved run its request
finds, or the request key of the run to make, or the refusal of the code with its line where it
has one; the backtest runs `ff.backtest.run`, reports its stages, and answers its run key."""

from datetime import date

import pytest
from pydantic import JsonValue

import fefat as ff
from fefat.backtest import RunConfig
from fefat.strategy import StrategyVersion
from fefat_app.execution import (
    BacktestOutput,
    BacktestSpec,
    ExecutionLimits,
    ExecutionProgress,
    ExecutionResult,
    ExecutionSucceeded,
    RefusedCode,
    RunLookupOutput,
    RunLookupSpec,
)
from fefat_app.executor.subprocess_executor import SubprocessExecutor
from fefat_app.runs import RequestedRun, RunToMake, SavedRunFound
from notebook_runs import store_with
from strategy_code import ES_BREAKOUT, HYPOTHESIS

ROOMY = ExecutionLimits(timeout_seconds=120, memory_bytes=8 * 1024**3)
WINDOW = (date(2026, 3, 5), date(2026, 3, 9))
DEFAULTS = {"lookback": 12, "stop_atr": 1.5}


def output_of(result: ExecutionResult) -> object:
    """What an execution that ran to its end gave."""
    assert isinstance(result, ExecutionSucceeded), result
    return result.output


def requested(
    version: StrategyVersion, settings: RunConfig | None = None, **parameters: JsonValue
) -> RequestedRun:
    return RequestedRun(
        strategy=version.name,
        version=version.version,
        hash=version.hash,
        parameters=parameters,
        start=WINDOW[0],
        end=WINDOW[1],
        settings=RunConfig() if settings is None else settings,
    )


def lookup_answer(executor: SubprocessExecutor, run: RequestedRun) -> object:
    output = output_of(executor.run(RunLookupSpec(run=run, limits=ROOMY), print))
    assert isinstance(output, RunLookupOutput)
    return output.answer


def test_a_lookup_and_a_backtest_answer_the_run_and_its_stages(
    executor: SubprocessExecutor,
) -> None:
    store_with("ohlcv-1m")
    run = requested(ff.strategy.save("breakout", ES_BREAKOUT, hypothesis=HYPOTHESIS))
    reports: list[ExecutionProgress] = []
    reported_again: list[ExecutionProgress] = []

    before = lookup_answer(executor, run)
    made = output_of(executor.run(BacktestSpec(run=run, limits=ROOMY), reports.append))
    after = lookup_answer(executor, run)
    again = output_of(executor.run(BacktestSpec(run=run, limits=ROOMY), reported_again.append))

    assert isinstance(before, RunToMake)
    assert before.request_key is not None
    assert (before.parameters, before.settings.provider) == (DEFAULTS, "synthetic")
    assert isinstance(made, BacktestOutput)
    assert [(each.percent, each.message) for each in reports] == [
        (30, "Loaded the data"),
        (50, "Computed the features and signals"),
        (60, "Running the engine"),
        (100, "Wrote the artifacts"),
    ]
    assert after == SavedRunFound(
        run_key=made.run_key,
        request_key=before.request_key,
        parameters=DEFAULTS,
        settings=before.settings,
    )
    assert again == made
    assert [(each.percent, each.message) for each in reported_again] == [
        (100, "Opened the saved run")
    ]


@pytest.mark.parametrize(
    ("settings", "parameters", "said"),
    [
        (None, {"lookback": "24"}, "Expected the strategy's parameters as its schema gives them"),
        (RunConfig(contract="NQH2026"), {}, "Expected a contract of ES, the strategy's root"),
    ],
)
def test_a_lookup_refuses_what_the_sdk_refuses_in_its_words(
    executor: SubprocessExecutor,
    settings: RunConfig | None,
    parameters: dict[str, JsonValue],
    said: str,
) -> None:
    store_with("ohlcv-1m")
    version = ff.strategy.save("breakout", ES_BREAKOUT, hypothesis=HYPOTHESIS)

    answer = lookup_answer(executor, requested(version, settings, **parameters))

    assert isinstance(answer, RefusedCode)
    assert answer.line is None
    assert said in answer.message


def test_a_version_whose_file_is_not_as_indexed_is_refused(executor: SubprocessExecutor) -> None:
    store_with("ohlcv-1m")
    version = ff.strategy.save("breakout", ES_BREAKOUT, hypothesis=HYPOTHESIS)
    another = version.model_copy(update={"hash": "f" * 64})

    answer = lookup_answer(executor, requested(another))

    assert isinstance(answer, RefusedCode)
    assert f"with the hash {'f' * 12} as indexed" in answer.message
