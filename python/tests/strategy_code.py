"""Strategy versions' code for the tests of step 5.2 (D-93): modules whose function `strategy`
gives a `SignalStrategy`, as `ff.strategy.save` takes them."""

BREAKOUT = """\
import polars as pl

import fefat as ff


def strategy(lookback: int = 12, stop_atr: float = 1.5) -> ff.SignalStrategy:
    close = pl.col("close")
    return ff.SignalStrategy(
        instrument="MES",
        timeframe="5m",
        features={
            "highest": close.rolling_max(lookback).shift(1),
            "atr": (pl.col("high") - pl.col("low")).rolling_mean(14),
        },
        long_entry=close > pl.col("highest"),
        short_entry=pl.lit(False),
        execution=ff.Execution(
            entry=ff.Market(),
            stop=ff.Stop(atr=stop_atr),
            targets=[ff.Target(r=2)],
            sizing=ff.Fixed(1),
        ),
    )
"""
"""The engine guide's breakout as a strategy version's code, its function on line 6."""
HYPOTHESIS = "A close above the highest of the hour before it runs on to twice its risk."
ES_BREAKOUT = BREAKOUT.replace('instrument="MES"', 'instrument="ES"')
"""The breakout on ES, which the synthetic fixtures hold (step 5.3)."""
WITH_A_SLOT = """\
import polars as pl

import fefat as ff


def strategy() -> ff.SignalStrategy:
    return ff.SignalStrategy(
        instrument="MES",
        timeframe="5m",
        features={{"read": {feature}}},
        long_entry={entry},
        short_entry=pl.lit(False),
        execution=ff.Execution(entry=ff.Market(), sizing=ff.Fixed(1)),
    )
"""
"""A strategy reading `feature` in a slot, entering where `entry` holds; its function on line 6,
its slot on line 10, its entry on line 11."""
