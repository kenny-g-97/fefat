"""The library's executions, step 5.2 (D-91, D-93): a strategy's code validated, a strategy version
saved, and a feature version saved, each in a runner of its own through the SDK, as a notebook
calls it; what the SDK refuses comes back as the runner's answer, with the line of the code the
refusal is at (Done means 2), and a validation writes nothing."""

import os

import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat_app.execution import (
    ExecutionLimits,
    ExecutionResult,
    ExecutionSucceeded,
    FeatureSaveOutput,
    FeatureSaveSpec,
    RefusedCode,
    SavedVersion,
    StrategySaveOutput,
    StrategySaveSpec,
    StrategyValidationOutput,
    StrategyValidationSpec,
    ValidStrategy,
)
from fefat_app.executor.subprocess_executor import SubprocessExecutor
from strategy_code import BREAKOUT, HYPOTHESIS, WITH_A_SLOT

ROOMY = ExecutionLimits(timeout_seconds=60, memory_bytes=8 * 1024**3)
GAP = """\
@ff.feature(params={"n": 3}, warmup=lambda n: n, outputs={"gap": "price_distance"})
def gap(bars: pl.LazyFrame, n: int) -> pl.Expr:
    return pl.col("close") - pl.col("close").rolling_mean(n)
"""
"""A feature's code, as `ff.features.from_source` takes it."""


def output_of(result: ExecutionResult) -> object:
    """What an execution that ran to its end gave."""
    assert isinstance(result, ExecutionSucceeded), result
    return result.output


def test_a_valid_strategy_comes_back_with_its_parameters_and_nothing_is_written(
    executor: SubprocessExecutor,
) -> None:
    output = output_of(executor.run(StrategyValidationSpec(code=BREAKOUT, limits=ROOMY), print))

    assert isinstance(output, StrategyValidationOutput)
    answer = output.answer
    assert isinstance(answer, ValidStrategy)
    assert (answer.instrument, answer.timeframe, answer.lint) == ("MES", "5m", ())
    assert sorted(answer.parameter_schema["properties"]) == ["lookback", "stop_atr"]
    assert not resolve_paths(os.environ).workspace_dir.exists()


def test_a_syntax_error_comes_back_refused_with_its_line(executor: SubprocessExecutor) -> None:
    # Done means 2, through the runner.
    broken = BREAKOUT.replace('pl.col("close")', 'pl.col("close") +')

    output = output_of(executor.run(StrategyValidationSpec(code=broken, limits=ROOMY), print))

    assert isinstance(output, StrategyValidationOutput)
    assert output.answer == RefusedCode(line=7, message="SyntaxError: invalid syntax")


def test_a_saved_version_and_the_features_it_pins_are_where_the_sdk_reads_them(
    executor: SubprocessExecutor,
) -> None:
    code = WITH_A_SLOT.format(feature="ff.indicators.rsi(14)", entry='pl.col("read") < 30')
    spec = StrategySaveSpec(
        name="oversold", code=code, hypothesis=HYPOTHESIS, changelog="First.", limits=ROOMY
    )

    output = output_of(executor.run(spec, print))

    assert isinstance(output, StrategySaveOutput)
    assert output.answer == SavedVersion(name="oversold", version=1)
    saved = ff.strategy.load("oversold", 1)
    assert (saved.changelog, saved.pinned_features[0].name) == ("First.", "rsi")
    assert ff.features.load("rsi", 1).hash == saved.pinned_features[0].hash


def test_a_feature_version_is_saved_where_the_sdk_reads_it(executor: SubprocessExecutor) -> None:
    output = output_of(executor.run(FeatureSaveSpec(name="gap", code=GAP, limits=ROOMY), print))

    assert isinstance(output, FeatureSaveOutput)
    assert output.answer == SavedVersion(name="gap", version=1)
    assert ff.features.load("gap", 1).code == GAP


@pytest.mark.parametrize(
    ("name", "code", "refusal"),
    [
        (
            "other",
            GAP,
            RefusedCode(
                line=None, message="Expected the code of feature other, got that of feature gap."
            ),
        ),
        (
            "gap",
            GAP.replace("return", "return return"),
            RefusedCode(line=3, message="SyntaxError: invalid syntax"),
        ),
    ],
)
def test_a_features_code_is_refused_in_the_sdks_words_with_its_line(
    executor: SubprocessExecutor, name: str, code: str, refusal: RefusedCode
) -> None:
    output = output_of(executor.run(FeatureSaveSpec(name=name, code=code, limits=ROOMY), print))

    assert isinstance(output, FeatureSaveOutput)
    assert output.answer == refusal
    assert not resolve_paths(os.environ).workspace_dir.exists()
