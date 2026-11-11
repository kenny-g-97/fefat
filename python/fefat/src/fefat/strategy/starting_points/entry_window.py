"""A breakout in the first two hours after the cash open runs on into the afternoon, so a position
closed before the session ends keeps the move without the risk of the night."""

from typing import Literal

import polars as pl

import fefat as ff


def strategy(
    side: Literal["long", "short", "both"] = "both", flat_by: str = "15:05"
) -> ff.SignalStrategy:
    close = pl.col("close")
    return ff.SignalStrategy(
        instrument="MES",
        timeframe="5m",
        features={
            "highest": close.rolling_max(12).shift(1),
            "lowest": close.rolling_min(12).shift(1),
            "atr": (pl.col("high") - pl.col("low")).rolling_mean(14),
        },
        long_entry=close > pl.col("highest") if side != "short" else pl.lit(False),
        short_entry=close < pl.col("lowest") if side != "long" else pl.lit(False),
        execution=ff.Execution(
            entry=ff.Market(),
            stop=ff.Stop(atr=1.5),
            targets=[ff.Target(r=2)],
            time=ff.TimeRules(
                tz="America/Chicago",
                windows=[ff.EntryWindow(start="08:30", end="10:30")],
                flat_by=flat_by,
            ),
            sizing=ff.Fixed(1),
        ),
    )
