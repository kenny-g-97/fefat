"""The executor's previews of step 4.5 in its warm runner (`01-architecture.md` section 6): a
preview gives each output's statistics as the SDK computes them, and a series downsampled to at
most a thousand points that keeps its highs and lows; the warm runner survives a preview that
fails, is started again after one that runs out of time or asks for another memory limit, and
ends with the executor, the preview it runs then failing; and a month of 5-minute bars, generated
(the step's amendment), previews again in the same runner in under a second (Done means 2)."""

import os
import threading
import time
from datetime import date
from pathlib import Path

import polars as pl
import pytest

import fefat as ff
from fefat.config import resolve_paths
from fefat.features.examples import rsi
from fefat_app.execution import (
    BarsReference,
    ExecutionFailed,
    ExecutionLimits,
    ExecutionProgress,
    ExecutionResult,
    ExecutionSucceeded,
    ExecutionTimedOut,
    FeaturePreviewOutput,
    FeaturePreviewSpec,
)
from fefat_app.executor.protocol import SERIES_POINTS
from fefat_app.executor.runner_process import RunnerProcess
from fefat_app.executor.subprocess_executor import SubprocessExecutor
from generated_minutes import SPRING, write_minutes
from local_server import running_runners

GIB = 1024**3
ROOMY = ExecutionLimits(timeout_seconds=120, memory_bytes=8 * GIB)
"""Limits no test preview but the ones testing them comes near."""
MONTH = BarsReference(
    instrument="ES", timeframe="5m", start=date(2026, 2, 2), end=date(2026, 2, 27)
)
"""February 2026 of ES at 5 minutes, a month of 5-minute bars, its warm-up read from January."""
FAILS = """\
@ff.feature(params={"n": 3}, outputs={"fails": "other"})
def fails(bars: pl.LazyFrame, n: BarCount) -> pl.Expr:
    raise ValueError("planted")
"""
LOOPS = """\
@ff.feature(params={"n": 3}, outputs={"loops": "other"})
def loops(bars: pl.LazyFrame, n: BarCount) -> pl.Expr:
    while True:
        pass
"""


@pytest.fixture(autouse=True)
def january_and_february() -> None:
    """ES's March contract from 2026-01-02, without the roll to June: the month and its warm-up."""
    write_minutes(SPRING[:1])


def previewed(
    executor: SubprocessExecutor,
    code: str,
    parameters: dict[str, object],
    limits: ExecutionLimits = ROOMY,
    reports: list[ExecutionProgress] | None = None,
) -> ExecutionResult:
    """How the preview of the feature `code` with `parameters` over `MONTH` ended."""
    kept: list[ExecutionProgress] = [] if reports is None else reports
    spec = FeaturePreviewSpec(code=code, parameters=parameters, bars=MONTH, limits=limits)
    return executor.run(spec, kept.append)


def output_of(result: ExecutionResult) -> FeaturePreviewOutput:
    assert isinstance(result, ExecutionSucceeded), result
    assert isinstance(result.output, FeaturePreviewOutput)
    return result.output


def test_a_preview_gives_the_sdk_s_statistics_and_a_series_that_keeps_the_extremes(
    warm_executor: SubprocessExecutor,
) -> None:
    reports: list[ExecutionProgress] = []

    output = output_of(previewed(warm_executor, rsi.code, {"n": 14}, reports=reports))

    computed = ff.features.compute({"rsi": rsi(n=14)}, "ES", "5m", MONTH.start, MONTH.end)
    every = computed.collect().get_column("rsi")
    finite = every.filter(every.is_finite())
    statistics = output.statistics["rsi"]
    assert (statistics.count, statistics.min, statistics.max, statistics.last) == (
        finite.len(),
        finite.min(),
        finite.max(),
        finite[-1],
    )
    assert statistics.mean == pytest.approx(finite.mean())
    assert statistics.std == pytest.approx(finite.std())
    assert statistics.missing_share == pytest.approx(1 - finite.len() / every.len())
    kept = [point.value for point in output.series]
    assert len(kept) <= SERIES_POINTS < finite.len()
    assert (min(kept), max(kept)) == (statistics.min, statistics.max)
    closes = [point.ts_close for point in output.series]
    assert closes == sorted(closes)
    assert {point.output for point in output.series} == {"rsi"}
    assert [report.percent for report in reports] == [10, 70, 90]


def test_the_warm_runner_survives_a_preview_that_fails(
    warm_executor: SubprocessExecutor,
) -> None:
    # The step's test: a preview that fails leaves its runner warm for the next.
    failed = previewed(warm_executor, FAILS, {"n": 3})
    runners = running_runners()

    succeeded = previewed(warm_executor, rsi.code, {"n": 14})

    assert isinstance(failed, ExecutionFailed), failed
    assert "ValueError: planted" in failed.error
    output_of(succeeded)
    assert len(runners) == 1
    assert running_runners() == runners


def test_a_preview_that_runs_out_of_time_starts_the_warm_runner_again(
    warm_executor: SubprocessExecutor,
) -> None:
    output_of(previewed(warm_executor, rsi.code, {"n": 14}))
    first = running_runners()

    timed_out = previewed(
        warm_executor, LOOPS, {"n": 3}, ExecutionLimits(timeout_seconds=3, memory_bytes=8 * GIB)
    )

    assert timed_out == ExecutionTimedOut()
    assert running_runners() == []
    output_of(previewed(warm_executor, rsi.code, {"n": 14}))
    again = running_runners()
    assert len(first) == len(again) == 1
    assert again != first


def test_a_preview_asking_for_another_memory_limit_starts_the_warm_runner_again(
    warm_executor: SubprocessExecutor,
) -> None:
    output_of(previewed(warm_executor, rsi.code, {"n": 14}))
    first = running_runners()

    output_of(
        previewed(
            warm_executor,
            rsi.code,
            {"n": 14},
            ExecutionLimits(timeout_seconds=120, memory_bytes=4 * GIB),
        )
    )

    again = running_runners()
    assert len(first) == len(again) == 1
    assert again != first


def test_a_warm_preview_of_a_month_of_five_minute_bars_takes_under_a_second_after_the_first(
    warm_executor: SubprocessExecutor,
) -> None:
    # Done means 2, with its generous bound: the second preview finds the runner warm, the SDK
    # imported, and the feature's values in the cache.
    began = time.perf_counter()
    first = previewed(warm_executor, rsi.code, {"n": 14})
    first_took = time.perf_counter() - began
    warm = running_runners()
    began = time.perf_counter()
    again = previewed(warm_executor, rsi.code, {"n": 14})
    again_took = time.perf_counter() - began

    print(f"a month of 5-minute RSI previewed in {first_took:.2f} s, again in {again_took:.2f} s")
    assert again == first
    assert output_of(again).statistics["rsi"].count > 4000
    assert again_took < 1.0
    assert len(warm) == 1
    assert running_runners() == warm


def test_closing_the_executor_ends_the_preview_it_runs_and_refuses_any_after(
    warm_executor: SubprocessExecutor,
) -> None:
    # As the server stops: a preview of a feature that never ends would hold its runner, and the
    # server, for its whole timeout.
    reports: list[ExecutionProgress] = []
    results: list[ExecutionResult] = []
    spec = FeaturePreviewSpec(code=LOOPS, parameters={"n": 3}, bars=MONTH, limits=ROOMY)
    previewing = threading.Thread(
        target=lambda: results.append(warm_executor.run(spec, reports.append))
    )
    previewing.start()
    deadline = time.monotonic() + 60
    while not reports:
        assert time.monotonic() < deadline, "Expected the preview to report within 60 s."
        time.sleep(0.05)

    began = time.monotonic()
    warm_executor.close()
    previewing.join(60)

    assert time.monotonic() - began < 10
    assert [type(result) for result in results] == [ExecutionFailed]
    with pytest.raises(ValueError, match="Expected an open executor for a preview"):
        previewed(warm_executor, rsi.code, {"n": 14})


def test_a_module_in_the_warm_runner_s_working_folder_shadows_nothing(
    warm_executor: SubprocessExecutor,
) -> None:
    # `python -m` would put the warm runner's working folder, which every preview shares, first
    # on its import path, where a file a preview wrote would hide a module of the same name.
    planted = resolve_paths(os.environ).executions_dir / "pydantic.py"
    planted.parent.mkdir(parents=True, exist_ok=True)
    planted.write_text('raise ImportError("planted")\n', encoding="utf-8")
    try:
        output_of(previewed(warm_executor, rsi.code, {"n": 14}))
    finally:
        warm_executor.close()
        planted.unlink()


def test_a_warm_runner_found_ended_at_the_sending_is_started_again(
    warm_executor: SubprocessExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_of(previewed(warm_executor, rsi.code, {"n": 14}))
    first = running_runners()
    sending = RunnerProcess.send
    refusals: list[Path] = []

    def ended_once(runner: RunnerProcess, folder: Path) -> None:
        if not refusals:
            refusals.append(folder)
            raise BrokenPipeError("planted: the runner ended since the look")
        sending(runner, folder)

    monkeypatch.setattr(RunnerProcess, "send", ended_once)

    output_of(previewed(warm_executor, rsi.code, {"n": 14}))

    again = running_runners()
    assert len(refusals) == 1
    assert len(first) == len(again) == 1
    assert again != first


def test_the_series_holds_each_output_of_a_feature_of_several(
    warm_executor: SubprocessExecutor,
) -> None:
    bands = """\
@ff.feature(params={"n": 20}, warmup=lambda n: n, outputs={"upper": "price", "lower": "price"})
def bands(bars: pl.LazyFrame, n: BarCount) -> dict[str, pl.Expr]:
    middle = pl.col("close").rolling_mean(n)
    return {"upper": middle + 1_000_000_000, "lower": middle - 1_000_000_000}
"""

    output = output_of(previewed(warm_executor, bands, {"n": 20}))

    assert set(output.statistics) == {"upper", "lower"}
    by_output = pl.DataFrame([point.model_dump() for point in output.series])
    counts = dict(by_output.group_by("output").len().iter_rows())
    assert set(counts) == {"upper", "lower"}
    assert max(counts.values()) <= SERIES_POINTS
