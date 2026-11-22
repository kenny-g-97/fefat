"""A run trades the instrument its settings name (step 5.6, D-114): it behaves as if its code
named that instrument, its record says so, it stays its saved version's, a feature keeps reading
the instrument it declares, and a run left on the code's own instrument keeps its key."""

import json
import os
import shutil

import polars as pl
import pytest

import fefat as ff
from fefat.backtest import Run, RunConfig
from fefat.backtest.artifacts import RECORD_FILE
from fefat.config import resolve_paths
from fefat.features import FeatureSpec, InstrumentInput
from notebook_runs import breakout, store_with
from strategy_code import ES_BREAKOUT, HYPOTHESIS
from test_backtest_run import breakout_reading_btc

PERPETUAL = "BTCUSDT-PERP"
WINDOW = ("2026-03-05", "2026-03-09")


@ff.feature(inputs=[InstrumentInput(root="ES")], outputs={"es_close": "price"})
def es_close(bars: pl.LazyFrame) -> pl.Expr:
    return pl.col("close_ES")


def breakout_with(feature: FeatureSpec) -> ff.SignalStrategy:
    """The breakout of the fixtures, written for ES, with `feature` beside it."""
    plain = breakout()
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features={**plain.features, "es_close": feature},
        long_entry=plain.long_entry,
        short_entry=plain.short_entry,
        execution=plain.execution,
    )


def test_a_run_trades_the_instrument_its_settings_name() -> None:
    store_with("ohlcv-1m", "funding")
    moved = ff.backtest.run(breakout(), *WINDOW, RunConfig(instrument=PERPETUAL))
    record = moved.record
    shutil.rmtree(resolve_paths(os.environ).runs_dir)

    written = ff.backtest.run(breakout().model_copy(update={"instrument": PERPETUAL}), *WINDOW)

    # Made again from nothing, the same code written for the perpetual is the same run.
    assert written.hash == moved.hash
    assert record.instrument.root == PERPETUAL
    assert record.strategy.spec["instrument"] == PERPETUAL
    assert record.config.instrument == PERPETUAL
    assert (record.config.fee_table, record.fee_table.name) == (
        "binance-default",
        "binance-default",
    )
    assert {dataset.root for dataset in record.datasets} == {PERPETUAL}


def test_the_reference_engine_replays_a_run_on_another_instrument() -> None:
    # The record names what the run traded, so explain reads ES's bars for code naming the
    # perpetual, and raises if the reference engine's fills are not the run's.
    store_with("ohlcv-1m")
    written_for_perpetual = breakout().model_copy(update={"instrument": PERPETUAL})

    run = ff.backtest.run(written_for_perpetual, *WINDOW, RunConfig(instrument="ES"))

    assert run.record.instrument.root == "ES"
    assert run.explain(run.trades.row(0, named=True)["entry_order"]).fills


def test_a_contract_of_the_codes_instrument_is_refused_on_another() -> None:
    store_with("ohlcv-1m")

    with pytest.raises(
        ValueError, match="Expected a contract of BTCUSDT-PERP, the root the run trades"
    ):
        ff.backtest.run(breakout(), *WINDOW, RunConfig(instrument=PERPETUAL, contract="ESH2026"))


def test_the_codes_own_instrument_named_is_the_run_left_out() -> None:
    store_with("ohlcv-1m")
    left_out = ff.backtest.run(breakout(), *WINDOW)

    named = ff.backtest.run(breakout(), *WINDOW, RunConfig(instrument="ES"))

    assert named.hash == left_out.hash
    assert left_out.record.config.instrument == "ES"


def test_a_record_written_before_the_setting_still_reads() -> None:
    store_with("ohlcv-1m")
    run = ff.backtest.run(breakout(), *WINDOW)
    path = run.folder / RECORD_FILE
    document = json.loads(path.read_bytes())
    del document["config"]["instrument"]
    path.write_text(json.dumps(document), encoding="utf-8")

    assert Run.open(run.folder).record.config.instrument is None


def test_a_run_on_another_instrument_stays_its_saved_versions() -> None:
    store_with("ohlcv-1m", "funding")
    code = ES_BREAKOUT.replace("ff.Stop(atr=stop_atr)", "ff.Stop(ticks=12)")
    version = ff.strategy.save("breakout", code, hypothesis=HYPOTHESIS)

    run = ff.backtest.run(version.strategy(), *WINDOW, RunConfig(instrument=PERPETUAL))

    pin = run.record.strategy.saved_version
    assert pin is not None
    assert (pin.name, pin.version, pin.hash) == ("breakout", 1, version.hash)
    assert run.record.instrument.root == PERPETUAL


def test_a_feature_keeps_reading_the_instrument_it_declares() -> None:
    # Signals from ES, trades on the perpetual, as the features write them.
    store_with("ohlcv-1m", "funding")

    run = ff.backtest.run(breakout_with(es_close()), *WINDOW, RunConfig(instrument=PERPETUAL))

    assert {dataset.root for dataset in run.record.datasets} == {"ES", PERPETUAL}
    closes = ff.market.load("ES", "5m", *WINDOW).collect().get_column("close").to_list()
    read = run.signals.get_column("es_close").drop_nulls().to_list()
    assert read
    assert set(read) <= set(closes)
    assert not any("its own bars" in warning for warning in run.record.warnings)


def test_a_feature_declaring_the_instrument_traded_is_warned_of() -> None:
    # The run stands, but the feature now compares the instrument with itself.
    store_with("ohlcv-1m", "funding")

    moved = ff.backtest.run(breakout_reading_btc(), *WINDOW, RunConfig(instrument=PERPETUAL))
    own = ff.backtest.run(breakout_reading_btc(), *WINDOW)

    assert {dataset.root for dataset in moved.record.datasets} == {PERPETUAL}
    assert [warning for warning in moved.record.warnings if "its own bars" in warning] == [
        "the feature btc_close declares BTCUSDT-PERP, the instrument this run trades, so it reads "
        "its own bars rather than another instrument's"
    ]
    assert not any("its own bars" in warning for warning in own.record.warnings)
