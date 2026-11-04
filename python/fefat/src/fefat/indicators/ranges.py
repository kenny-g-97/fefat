"""Distances of price (step 3.5): the true range, the average true range, and the standard
deviation of the closes, in the bars' 1e-9 units of price, the units in which the execution
template reads a distance (`ff.Stop(atr=1.5)`, F-RND-01), and the z-score of the close, as
TA-Lib computes them; and the realised volatility of the closes' log returns (step 3.6)."""

import polars as pl

from fefat.features.definition import BarCount, TwoOrMoreBars, feature
from fefat.indicators.smoothing import exponential_average


def true_ranges() -> pl.Expr:
    """Each bar's true range, its high less its low, widened to the close before it, as TA-Lib's
    TRANGE: null on the first bar, which has no close before it."""
    previous = pl.col("close").shift(1)
    widened = pl.max_horizontal("high", previous) - pl.min_horizontal("low", previous)
    return pl.when(previous.is_not_null()).then(widened)


@feature(warmup=1, outputs={"true_range": "price_distance"})
def true_range(bars: pl.LazyFrame) -> pl.Expr:
    """Each bar's true range, its high less its low, widened to the close before it, TA-Lib's
    TRANGE, from the second bar on."""
    return true_ranges()


@feature(params={"n": 14}, warmup=lambda n: 25 * n, outputs={"atr": "price_distance"})
def atr(bars: pl.LazyFrame, n: BarCount) -> pl.Expr:
    """The average true range over `n` bars, TA-Lib's ATR with Wilder's smoothing: seeded with
    the simple average of the first `n` true ranges, from the second bar on, then each true
    range weighing 1 / n."""
    ranges = true_ranges()
    return exponential_average(ranges, 1 / n, ranges.rolling_mean(n), n)


@feature(params={"n": 20}, warmup=lambda n: n - 1, outputs={"standard_deviation": "price_distance"})
def standard_deviation(bars: pl.LazyFrame, n: TwoOrMoreBars) -> pl.Expr:
    """The standard deviation of the last `n` closes as a population's, TA-Lib's STDDEV."""
    return pl.col("close").rolling_std(n, ddof=0)


@feature(params={"n": 20}, warmup=lambda n: n - 1, outputs={"z_score": "ratio"})
def z_score(bars: pl.LazyFrame, n: TwoOrMoreBars) -> pl.Expr:
    """How many standard deviations the close lies above the simple average of the last `n`
    closes, TA-Lib's SMA and STDDEV, below it when negative; null where the closes have not
    moved."""
    close = pl.col("close")
    return (close - close.rolling_mean(n)) / close.rolling_std(n, ddof=0)


@feature(params={"n": 20}, warmup=lambda n: n, outputs={"realised_volatility": "ratio"})
def realised_volatility(bars: pl.LazyFrame, n: BarCount) -> pl.Expr:
    """The realised volatility of the last `n` bars: the square root of the sum of the squares of
    their log returns, close to close, not annualised; null where a close is not above zero, as a
    spliced crude oil's can be, whose return has no logarithm."""
    close, previous = pl.col("close"), pl.col("close").shift(1)
    returns = pl.when((close > 0) & (previous > 0)).then((close / previous).log())
    return returns.pow(2).rolling_sum(n).sqrt()
