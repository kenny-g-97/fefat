"""Bands and channels around price (step 3.5): Bollinger bands, Donchian channels, and Keltner
channels, levels in the bars' 1e-9 units of price, as TA-Lib computes them or composes them."""

from typing import Annotated

import polars as pl
from pydantic import Field

from fefat.features.definition import BarCount, TwoOrMoreBars, feature
from fefat.indicators.ranges import true_ranges
from fefat.indicators.smoothing import exponential_average

Multiple = Annotated[float, Field(gt=0)]
"""A multiple of a distance, above zero, as a band's width in standard deviations or ATRs."""


@feature(
    params={"n": 20, "deviations": 2.0},
    warmup=lambda n: n - 1,
    outputs={
        "middle": "price",
        "upper": "price",
        "lower": "price",
        "band_width": "ratio",
        "percent_b": "ratio",
    },
)
def bollinger(bars: pl.LazyFrame, n: TwoOrMoreBars, deviations: Multiple) -> dict[str, pl.Expr]:
    """Bollinger bands, TA-Lib's BBANDS with a simple average: the simple average of the last `n`
    closes, and bands `deviations` standard deviations of those closes, a population's, above and
    below it; the band width, the bands' distance over the average; and %b, where the close lies
    between the bands, 0 at the lower and 1 at the upper, null where the closes have not moved, as
    the band width is where the average is zero."""
    close = pl.col("close")
    middle = close.rolling_mean(n)
    offset = deviations * close.rolling_std(n, ddof=0)
    upper, lower = middle + offset, middle - offset
    return {
        "middle": middle,
        "upper": upper,
        "lower": lower,
        "band_width": pl.when(middle != 0).then((upper - lower) / middle),
        "percent_b": (close - lower) / (upper - lower),
    }


@feature(
    params={"n": 20},
    warmup=lambda n: n - 1,
    outputs={"upper": "price", "lower": "price", "middle": "price"},
)
def donchian(bars: pl.LazyFrame, n: BarCount) -> dict[str, pl.Expr]:
    """Donchian channels: the highest high and the lowest low of the last `n` bars, the bar's
    own included, TA-Lib's MAX and MIN of them, and the middle between the two. A close above the
    channel of the bars before it reads `upper` a bar back, `pl.col("channel_upper").shift(1)`."""
    upper, lower = pl.col("high").rolling_max(n), pl.col("low").rolling_min(n)
    return {"upper": upper, "lower": lower, "middle": (upper + lower) / 2}


@feature(
    params={"n": 20, "atr_n": 10, "multiplier": 2.0},
    warmup=lambda n, atr_n: 25 * max(n, atr_n),
    outputs={"middle": "price", "upper": "price", "lower": "price"},
)
def keltner(
    bars: pl.LazyFrame, n: BarCount, atr_n: BarCount, multiplier: Multiple
) -> dict[str, pl.Expr]:
    """Keltner channels as charts draw them today (your choice, D-75): the exponential average
    of the closes over `n` bars, as `ema` gives it, and channels `multiplier` average true ranges
    over `atr_n` bars, as `atr` gives it, above and below it. TA-Lib has none, so their golden is
    TA-Lib's EMA and ATR."""
    close, ranges = pl.col("close"), true_ranges()
    middle = exponential_average(close, 2 / (n + 1), close.rolling_mean(n), n - 1)
    average_range = exponential_average(ranges, 1 / atr_n, ranges.rolling_mean(atr_n), atr_n)
    offset = multiplier * average_range
    return {"middle": middle, "upper": middle + offset, "lower": middle - offset}
