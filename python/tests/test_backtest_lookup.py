"""The lookup of saved runs by their request (step 3.7, Done means 2): a file beside the saved runs,
keyed by the strategy's document with its features' versions and parameters and its
expressions, the window, the settings, and what the run reads, names the run its request made,
so that an identical run opens the saved one without loading bars or evaluating signals; a run
whose strategy, settings, or data differ, or whose saved run is gone, misses and runs."""

import os
import shutil
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from polars.expr.meta import ExprMetaNameSpace

import fefat as ff
import fefat.backtest.runs as runs
from fefat.backtest import RunConfig
from fefat.backtest.requests import request_of
from fefat.backtest.run_inputs import RunInputs, run_inputs
from fefat.config import resolve_paths
from fefat.market.fidelity import ONE_MINUTE
from notebook_runs import breakout, features_of_cell, store_with

WINDOW = ("2026-03-05", "2026-03-09")
MOMENTUM = """\
@ff.feature(warmup=3, outputs={"momentum_up": "flag"})
def momentum_up(bars: pl.LazyFrame) -> pl.Expr:
    change = pl.col("close") - pl.col("close").shift(3)
    return change > 0
"""
"""A feature as a notebook cell defines it: whether the close rose over three bars."""


def requests_kept() -> list[Path]:
    return sorted((resolve_paths(os.environ).runs_dir / "requests").glob("*.json"))


def counted_inputs(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """The calls of `run_inputs`, which loads a run's bars and evaluates its signals, from now on."""
    calls: list[object] = []

    def counted(*arguments: Any) -> RunInputs:
        calls.append(arguments)
        return run_inputs(*arguments)

    monkeypatch.setattr(runs, "run_inputs", counted)
    return calls


def breakout_entering(entry: pl.Expr) -> ff.SignalStrategy:
    """The breakout of the fixtures with another entry."""
    strategy = breakout()
    return ff.SignalStrategy(
        instrument=strategy.instrument,
        timeframe=strategy.timeframe,
        features=dict(strategy.features),
        long_entry=entry,
        short_entry=pl.lit(False),
        execution=strategy.execution,
    )


def test_an_identical_run_opens_its_saved_run_without_loading_bars_or_evaluating_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    first = ff.backtest.run(breakout(), *WINDOW)

    def refused(*_: object) -> object:
        raise AssertionError("Expected the saved run, got its bars loaded and signals evaluated")

    monkeypatch.setattr(runs, "run_inputs", refused)
    with pytest.warns(UserWarning, match="F-FEE-01"):
        again = ff.backtest.run(breakout(), *WINDOW)

    assert again.hash == first.hash
    assert again.record == first.record
    assert len(requests_kept()) == 1


def test_a_run_whose_strategy_settings_or_window_differ_misses_and_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_with("ohlcv-1m")
    calls = counted_inputs(monkeypatch)
    at_or_above = breakout_entering(pl.col("close") >= pl.col("highest"))

    hashes = {
        ff.backtest.run(breakout(), *WINDOW).hash,
        ff.backtest.run(at_or_above, *WINDOW).hash,
        ff.backtest.run(breakout(), *WINDOW, RunConfig(latency_ms=500)).hash,
        ff.backtest.run(breakout(), "2026-03-05", "2026-03-06").hash,
    }

    assert len(calls) == 4
    assert len(hashes) == 4
    assert len(requests_kept()) == 4


def test_a_run_after_data_arrived_in_its_dates_misses_and_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The fidelity is named, so that the settings stay the same while the data changes.
    store_with("ohlcv-1m")
    calls = counted_inputs(monkeypatch)
    ff.backtest.run(breakout(), *WINDOW, RunConfig(fidelity=ONE_MINUTE))
    store_with("ohlcv-1s")

    ff.backtest.run(breakout(), *WINDOW, RunConfig(fidelity=ONE_MINUTE))

    assert len(calls) == 2


def test_a_perpetuals_run_misses_once_its_funding_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    # The plan's review: a perpetual's funding keys its run, which the feature cache's pins of
    # trades, TBBO, and bars leave out, so the request reads it too.
    store_with("trades", "ohlcv-1s", "ohlcv-1m", "funding")
    funding = (
        resolve_paths(os.environ).data_dir
        / "synthetic/funding/root=BTCUSDT-PERP/contract=BTCUSDT-PERP/part.parquet"
    )
    calls = counted_inputs(monkeypatch)
    with pytest.warns(UserWarning, match="binance-default"):
        before = ff.backtest.run(long_btc(), "2026-03-07", "2026-03-07")
    rates = pl.read_parquet(funding)
    rates.with_columns(pl.col("funding_rate") * 2).write_parquet(funding)

    with pytest.warns(UserWarning, match="binance-default"):
        after = ff.backtest.run(long_btc(), "2026-03-07", "2026-03-07")

    assert len(calls) == 2
    assert after.hash != before.hash


def test_a_request_whose_run_is_gone_misses_runs_and_is_kept_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_with("ohlcv-1m")
    first = ff.backtest.run(breakout(), *WINDOW)
    shutil.rmtree(first.folder)
    calls = counted_inputs(monkeypatch)

    again = ff.backtest.run(breakout(), *WINDOW)

    assert len(calls) == 1
    assert again.hash == first.hash
    assert (again.folder / "run.json").is_file()
    assert ff.backtest.run(breakout(), *WINDOW).hash == first.hash
    assert len(calls) == 1


def test_a_feature_version_whose_values_agree_finds_the_run_of_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Its own request is kept with the first version's run, whose record names the first.
    store_with("ohlcv-1m")
    first = features_of_cell(MOMENTUM)["momentum_up"]
    renamed = features_of_cell(MOMENTUM.replace("change", "difference"))["momentum_up"]
    strategies = [breakout_on(each()) for each in (first, renamed)]
    made = [ff.backtest.run(strategy, *WINDOW) for strategy in strategies]
    calls = counted_inputs(monkeypatch)

    again = ff.backtest.run(strategies[1], *WINDOW)

    assert calls == []
    assert made[0].hash == made[1].hash == again.hash
    assert again.record.strategy.feature_versions[0].hash == first.hash
    assert len(requests_kept()) == 2


def test_a_strategy_that_calls_a_python_function_runs_without_its_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The code review: Polars writes a Python function only with cloudpickle, and then a
    # function of a module by its name alone, so an edit of its code would leave the request as
    # it was; a strategy calling Python keys no request, here even where Polars writes the
    # function, and runs as before.
    store_with("ohlcv-1m")
    strategy = breakout_entering(
        (pl.col("close") > pl.col("highest")).map_elements(bool, return_dtype=pl.Boolean)
    )
    with monkeypatch.context() as written:
        written.setattr(ExprMetaNameSpace, "serialize", lambda *_, **__: "my_signals.rule")
        request = request_of(strategy, *WINDOW, RunConfig(), resolve_paths(os.environ))

    with pytest.warns(UserWarning):
        run = ff.backtest.run(strategy, *WINDOW)

    assert request is None
    assert requests_kept() == []
    assert run.record.summary.trades > 0


def breakout_on(momentum: ff.features.FeatureSpec) -> ff.SignalStrategy:
    """The breakout of the fixtures, entering where `momentum` is up as well."""
    strategy = breakout()
    return ff.SignalStrategy(
        instrument=strategy.instrument,
        timeframe=strategy.timeframe,
        features={**strategy.features, "momentum": momentum},
        long_entry=(pl.col("close") > pl.col("highest")) & pl.col("momentum"),
        short_entry=pl.lit(False),
        execution=strategy.execution,
    )


def long_btc() -> ff.SignalStrategy:
    """A long of 0.1 BTC from 01:00 to 23:00 UTC, without a stop."""
    utc = pl.from_epoch("ts_close", time_unit="ns")
    return ff.SignalStrategy(
        instrument="BTCUSDT-PERP",
        timeframe="5m",
        long_entry=(utc.dt.hour() == 1) & (utc.dt.minute() == 0),
        short_entry=pl.lit(False),
        long_exit=(utc.dt.hour() == 23) & (utc.dt.minute() == 0),
        execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(0.1)),
    )
