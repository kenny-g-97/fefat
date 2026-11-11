"""A five-minute close above the highest close of the hour before it starts a move that reaches
twice its risk more often than it reaches its stop."""

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
