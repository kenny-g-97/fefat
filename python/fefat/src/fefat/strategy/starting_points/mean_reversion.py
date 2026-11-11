"""A fall that takes the five-minute RSI below its oversold level is followed by a bounce back to
the middle of its range."""

import polars as pl

import fefat as ff


def strategy(oversold: float = 30.0, long_only: bool = True) -> ff.SignalStrategy:
    rsi = pl.col("rsi")
    return ff.SignalStrategy(
        instrument="MES",
        timeframe="5m",
        features={"rsi": ff.indicators.rsi(14), "atr": ff.indicators.atr(14)},
        long_entry=rsi < oversold,
        short_entry=pl.lit(False) if long_only else rsi > 100 - oversold,
        long_exit=rsi > 50,
        short_exit=rsi < 50,
        execution=ff.Execution(entry=ff.Market(), stop=ff.Stop(atr=2.0), sizing=ff.Fixed(1)),
    )
