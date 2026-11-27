"""A saved run's reproduction in the executor (step 5.10, D-91, D-126): a backtest spec that
reproduces a saved run builds its version in a runner of its own and runs it again into FEFAT's
cache folder, reporting its stages, and answers its trades matched by their table's hash, leaving
no folder; trades that differ answer both hashes and keep the reproduction; and a version whose
file changed since it was indexed is refused as the reproduction's answer, not as a failure."""

import os

import fefat_engine
import polars as pl
import pytest

import fefat as ff
import fefat.backtest.reproductions as reproductions
from fefat.backtest import Run, RunConfig
from fefat.config import resolve_paths
from fefat_app.execution import (
    BacktestOutput,
    BacktestSpec,
    ExecutionLimits,
    ExecutionProgress,
    ExecutionSucceeded,
)
from fefat_app.executor.backtests import backtest_output
from fefat_app.executor.subprocess_executor import SubprocessExecutor
from fefat_app.reproductions import (
    REPRODUCTIONS_FOLDER,
    ReproductionDiffered,
    ReproductionMatched,
    ReproductionRefused,
)
from fefat_app.runs import RequestedRun
from notebook_runs import store_with
from strategy_code import ES_BREAKOUT, HYPOTHESIS
from test_backtest_reproduce import without_its_last_trade

ROOMY = ExecutionLimits(timeout_seconds=120, memory_bytes=8 * 1024**3)


@pytest.fixture
def saved() -> Run:
    """Version 1 of the breakout and its run on the fixtures' minute bars."""
    store_with("ohlcv-1m")
    version = ff.strategy.save("breakout", ES_BREAKOUT, hypothesis=HYPOTHESIS)
    return ff.backtest.run(version.strategy(), "2026-03-05", "2026-03-09")


def reproducing(run: Run) -> BacktestSpec:
    """The spec that reproduces `run`, from the version and the settings its record names."""
    pin = run.record.strategy.saved_version
    assert pin is not None
    requested = RequestedRun(
        strategy=pin.name,
        version=pin.version,
        hash=pin.hash,
        parameters=pin.parameters,
        start=run.record.window.start,
        end=run.record.window.end,
        settings=RunConfig.model_validate(run.config.model_dump()),
    )
    return BacktestSpec(run=requested, limits=ROOMY, reproduces=run.hash)


def test_a_saved_run_reproduced_answers_its_trades_matched_and_leaves_no_folder(
    executor: SubprocessExecutor, saved: Run
) -> None:
    reports: list[ExecutionProgress] = []

    result = executor.run(reproducing(saved), reports.append)

    assert isinstance(result, ExecutionSucceeded), result
    assert result.output == BacktestOutput(
        run_key=saved.hash,
        reproduction=ReproductionMatched(trades_hash=fefat_engine.table_hash(saved.trades)),
    )
    assert [(each.percent, each.message) for each in reports] == [
        (30, "Loaded the data"),
        (50, "Computed the features and signals"),
        (60, "Running the engine"),
        (100, "Wrote the artifacts"),
    ]
    assert not (resolve_paths(os.environ).cache_dir / REPRODUCTIONS_FOLDER / saved.hash).exists()


def test_trades_that_differ_answer_both_hashes_and_keep_the_reproduction(
    saved: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    with monkeypatch.context() as planted:
        planted.setattr(reproductions, "engine_run", without_its_last_trade)
        output = backtest_output(reproducing(saved), lambda reported: None)

    kept = resolve_paths(os.environ).cache_dir / REPRODUCTIONS_FOLDER / saved.hash
    differed = output.reproduction
    assert isinstance(differed, ReproductionDiffered)
    assert differed.saved_trades_hash == fefat_engine.table_hash(saved.trades)
    assert differed.reproduced_trades_hash != differed.saved_trades_hash
    assert output.run_key == saved.hash
    assert pl.read_parquet(kept / "trades.parquet").height == saved.trades.height - 1


def test_a_version_whose_file_changed_since_it_was_indexed_is_refused_as_the_answer(
    executor: SubprocessExecutor, saved: Run
) -> None:
    spec = reproducing(saved)
    replaced = spec.model_copy(update={"run": spec.run.model_copy(update={"hash": "0" * 64})})

    result = executor.run(replaced, print)

    assert isinstance(result, ExecutionSucceeded), result
    assert isinstance(result.output, BacktestOutput)
    refused = result.output.reproduction
    assert isinstance(refused, ReproductionRefused)
    assert "its file was replaced after it was indexed" in refused.reason
