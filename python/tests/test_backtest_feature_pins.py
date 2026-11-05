"""The features a run reads by version (step 3.7, Done means 2, D-71): a run of a strategy whose
slots hold library features records each one's name, version, content hash, and parameters in
`run.json`, saving it in the library first; a version whose values differ changes the run key,
since the signal frame holds each feature's values (D-62), and one whose values are the same
gives the same run, whose record names the version it was first run with."""

import json

import polars as pl
import pytest

import fefat as ff
from fefat.backtest import FeaturePin, Run
from fefat.features import FeatureSpec, combine
from notebook_runs import features_of_cell, store_with

MOMENTUM = """\
@ff.feature(warmup=3, outputs={"momentum_up": "flag"})
def momentum_up(bars: pl.LazyFrame) -> pl.Expr:
    change = pl.col("close") - pl.col("close").shift(3)
    return change > 0
"""
"""A feature as a notebook cell defines it: whether the close rose over three bars."""


@pytest.fixture(autouse=True)
def fixture_store() -> None:
    """The fixtures' ES trades, 1-second, and 1-minute bars in `FEFAT_DATA_DIR`."""
    store_with("trades", "ohlcv-1s", "ohlcv-1m")


def strategy(features: dict[str, FeatureSpec], long_entry: pl.Expr) -> ff.SignalStrategy:
    return ff.SignalStrategy(
        instrument="ES",
        timeframe="5m",
        features=features,
        long_entry=long_entry,
        short_entry=pl.lit(False),
        execution=ff.Execution(
            entry=ff.Market(),
            stop=ff.Stop(ticks=12),
            targets=[ff.Target(ticks=24)],
            sizing=ff.Fixed(1),
        ),
    )


def test_a_strategy_of_two_library_features_runs_and_its_record_lists_their_versions() -> None:
    # The step's test: two features read from the library by name and version, a combination
    # and an indicator, run end to end, and run.json lists their version hashes.
    rsi = ff.indicators.rsi
    stretch = combine.define("rsi_stretch", rsi(7) - combine.rolling_mean(rsi(7), 5))
    saved = ff.features.save(stretch)
    features = {
        "stretch": ff.features.ref("rsi_stretch", version=saved.version),
        "rsi": ff.features.ref("rsi", version=1, n=7),
    }

    run = ff.backtest.run(
        strategy(features, (pl.col("stretch") > 0) & (pl.col("rsi") > 50)),
        "2026-03-09",
        "2026-03-09",
    )

    written = json.loads((run.folder / "run.json").read_text(encoding="utf-8"))
    assert written["strategy"]["feature_versions"] == [
        {
            "slot": "stretch",
            "name": "rsi_stretch",
            "version": 1,
            "hash": stretch.hash,
            "parameters": {},
        },
        {"slot": "rsi", "name": "rsi", "version": 1, "hash": rsi.hash, "parameters": {"n": 7}},
    ]
    assert Run.open(run.folder).record == run.record
    assert run.record.summary.trades > 0


def test_a_run_saves_the_features_it_pins_in_the_library() -> None:
    rsi, atr = ff.indicators.rsi, ff.indicators.atr

    run = ff.backtest.run(
        strategy({"rsi": rsi(7), "atr": atr(7)}, pl.col("rsi") > 50), "2026-03-09", "2026-03-09"
    )

    assert run.record.strategy.feature_versions == (
        FeaturePin(slot="rsi", name="rsi", version=1, hash=rsi.hash, parameters={"n": 7}),
        FeaturePin(slot="atr", name="atr", version=1, hash=atr.hash, parameters={"n": 7}),
    )
    assert ff.features.library().select("name", "version").rows() == [("atr", 1), ("rsi", 1)]
    assert run.record.strategy.features == ("rsi", "atr")


def test_only_a_version_whose_values_differ_changes_the_run_key() -> None:
    # The amendment: the run key stays the hash of what the engine read, so a version whose
    # code differs but whose values are the same, a local renamed, gives the run of the first,
    # whose record names the first, as two fee tables with the same schedules share a key.
    first = features_of_cell(MOMENTUM)["momentum_up"]
    renamed = features_of_cell(MOMENTUM.replace("change", "difference"))["momentum_up"]
    slower = features_of_cell(MOMENTUM.replace("shift(3)", "shift(4)"))["momentum_up"]

    runs = [
        ff.backtest.run(
            strategy({"momentum": each()}, pl.col("momentum")), "2026-03-06", "2026-03-09"
        )
        for each in (first, renamed, slower)
    ]

    assert len({first.hash, renamed.hash, slower.hash}) == 3
    assert runs[0].hash == runs[1].hash != runs[2].hash
    pinned = [run.record.strategy.feature_versions[0] for run in runs]
    assert [(pin.version, pin.hash) for pin in pinned] == [
        (1, first.hash),
        (1, first.hash),
        (2, slower.hash),
    ]
