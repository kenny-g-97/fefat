"""Moving averages of the closes (step 3.5): simple, exponential, and weighted, and MACD, as
TA-Lib computes them, in the bars' 1e-9 units of price."""

import polars as pl

from fefat.features.definition import BarCount, feature
from fefat.indicators.smoothing import exponential_average


@feature(params={"n": 20}, warmup=lambda n: n - 1, outputs={"sma": "price"})
def sma(bars: pl.LazyFrame, n: BarCount) -> pl.Expr:
    """The simple moving average of the last `n` closes, TA-Lib's SMA."""
    return pl.col("close").rolling_mean(n)


@feature(params={"n": 20}, warmup=lambda n: 25 * n, outputs={"ema": "price"})
def ema(bars: pl.LazyFrame, n: BarCount) -> pl.Expr:
    """The exponential moving average of the closes, TA-Lib's EMA: seeded with the simple
    average of the first `n` closes, then each close weighing 2 / (n + 1) against it."""
    close = pl.col("close")
    return exponential_average(close, 2 / (n + 1), close.rolling_mean(n), n - 1)


@feature(params={"n": 20}, warmup=lambda n: n - 1, outputs={"wma": "price"})
def wma(bars: pl.LazyFrame, n: BarCount) -> pl.Expr:
    """The weighted moving average of the last `n` closes, the latest weighing n, the one before
    it n - 1, and so on down to 1, TA-Lib's WMA."""
    return pl.col("close").rolling_mean(n, weights=[float(weight) for weight in range(1, n + 1)])


@feature(
    params={"fast": 12, "slow": 26, "signal": 9},
    warmup=lambda fast, slow, signal: 25 * max(fast, slow, signal),
    outputs={"macd": "price_distance", "signal": "price_distance", "histogram": "price_distance"},
)
def macd(
    bars: pl.LazyFrame, fast: BarCount, slow: BarCount, signal: BarCount
) -> dict[str, pl.Expr]:
    """MACD, TA-Lib's: the exponential average of the closes over `fast` bars less that over
    `slow` bars, both seeded on the slow average's first bar, the fast one with the simple
    average of the `fast` closes up to it; its signal, the exponential average of MACD over
    `signal` bars, seeded with the simple average of its first `signal` values; and the
    histogram, MACD less its signal, all three from the signal's first value on. A fast period
    at or above the slow one is refused when the feature is evaluated, where TA-Lib swaps them,
    since a feature's parameters are each checked alone when it is called."""
    if fast >= slow:
        raise ValueError(
            f"Expected the fast period of macd below its slow one, got fast={fast} and slow={slow}."
        )
    close, start, first = pl.col("close"), slow - 1, slow + signal - 2
    fast_average = exponential_average(close, 2 / (fast + 1), close.rolling_mean(fast), start)
    slow_average = exponential_average(close, 2 / (slow + 1), close.rolling_mean(slow), start)
    line = fast_average - slow_average
    average = exponential_average(line, 2 / (signal + 1), line.rolling_mean(signal), first)
    return {
        "macd": pl.when(pl.int_range(pl.len()) >= first).then(line),
        "signal": average,
        "histogram": line - average,
    }
