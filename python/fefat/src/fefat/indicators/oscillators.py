"""Oscillators and momentum (step 3.5): RSI, the stochastic, the rate of change and momentum,
the average directional index with its directional indicators, and on-balance volume, as TA-Lib
computes them. Where TA-Lib divides by zero and gives 0 or 50, as the RSI of closes that have not
moved, these give null: no value, which a strategy reads as no signal."""

from typing import Annotated

import polars as pl
from pydantic import Field

from fefat.features.definition import BarCount, feature
from fefat.indicators.smoothing import exponential_average, true_ranges


@feature(params={"n": 14}, warmup=lambda n: 25 * n, outputs={"rsi": "ratio"})
def rsi(bars: pl.LazyFrame, n: BarCount) -> pl.Expr:
    """The relative strength index of the closes over `n` bars, from 0 to 100, TA-Lib's RSI with
    Wilder's smoothing: 100 times the average rise over the average rise and fall, each average
    seeded with the simple average of the first `n` changes, then each change weighing 1 / n."""
    change = pl.col("close").diff()
    rise, fall = change.clip(lower_bound=0), (-change).clip(lower_bound=0)
    average_rise = exponential_average(rise, 1 / n, rise.rolling_mean(n), n)
    average_fall = exponential_average(fall, 1 / n, fall.rolling_mean(n), n)
    return 100 * (average_rise / (average_rise + average_fall))


@feature(
    params={"n": 14, "k_smoothing": 3, "d_smoothing": 3},
    warmup=lambda n, k_smoothing, d_smoothing: n + k_smoothing + d_smoothing - 3,
    outputs={"percent_k": "ratio", "percent_d": "ratio"},
)
def stochastic(
    bars: pl.LazyFrame, n: BarCount, k_smoothing: BarCount, d_smoothing: BarCount
) -> dict[str, pl.Expr]:
    """The slow stochastic, TA-Lib's STOCH with simple averages: where the close lies in the
    range of the last `n` bars, from 0 at its low to 100 at its high, averaged over `k_smoothing`
    bars for %K, and %K averaged over `d_smoothing` bars for %D, both from %D's first value on."""
    lowest = pl.col("low").rolling_min(n)
    position = 100 * ((pl.col("close") - lowest) / (pl.col("high").rolling_max(n) - lowest))
    percent_k = position.rolling_mean(k_smoothing)
    shown = pl.int_range(pl.len()) >= n + k_smoothing + d_smoothing - 3
    return {
        "percent_k": pl.when(shown).then(percent_k),
        "percent_d": percent_k.rolling_mean(d_smoothing),
    }


@feature(params={"n": 10}, warmup=lambda n: n, outputs={"roc": "ratio"})
def roc(bars: pl.LazyFrame, n: BarCount) -> pl.Expr:
    """The rate of change of the close over `n` bars in percent, TA-Lib's ROC."""
    close = pl.col("close")
    return 100 * (close / close.shift(n) - 1)


@feature(params={"n": 10}, warmup=lambda n: n, outputs={"momentum": "price_distance"})
def momentum(bars: pl.LazyFrame, n: BarCount) -> pl.Expr:
    """The close less the close `n` bars before it, TA-Lib's MOM."""
    close = pl.col("close")
    return close - close.shift(n)


@feature(
    params={"n": 14},
    warmup=lambda n: 50 * n,
    outputs={"adx": "ratio", "plus_di": "ratio", "minus_di": "ratio"},
)
def adx(bars: pl.LazyFrame, n: Annotated[int, Field(ge=2)]) -> pl.LazyFrame:
    """Wilder's average directional index and its directional indicators, TA-Lib's ADX,
    PLUS_DI, and MINUS_DI. A bar's upward move, its high above the high before it, counts when it
    outdoes its downward move, its low below the low before it, and the other way round; +DI and
    -DI are 100 times their averages over the true range's, each seeded from the sum of its first
    n - 1 values and then weighing each 1 / n, from bar `n` on. ADX averages 100 |+DI - -DI| /
    (+DI + -DI) alike, seeded with the simple average of its first `n` values, from bar 2n - 1
    on. Its two stages of smoothing forget more slowly than one, hence a warm-up of 50 n. It is
    worked out in stages on the bars' frame, each computed once, where expressions nested in one
    another would compute the averages again in each."""
    up, down = pl.col("high").diff(), -pl.col("low").diff()
    averages = {
        name: exponential_average(pl.col(name), 1 / n, pl.col(name).rolling_sum(n - 1) / n, n - 1)
        for name in ("upward", "downward", "true_range")
    }
    moves = bars.with_columns(
        upward=pl.when((up > down) & (up > 0)).then(up).otherwise(0),
        downward=pl.when((down > up) & (down > 0)).then(down).otherwise(0),
        true_range=true_ranges(),
    ).with_columns(**averages)
    shown = pl.int_range(pl.len()) >= n
    indicators = moves.with_columns(
        plus_di=pl.when(shown).then(100 * (pl.col("upward") / pl.col("true_range"))),
        minus_di=pl.when(shown).then(100 * (pl.col("downward") / pl.col("true_range"))),
    )
    plus_di, minus_di = pl.col("plus_di"), pl.col("minus_di")
    index = (100 * ((plus_di - minus_di).abs() / (plus_di + minus_di))).fill_nan(None)
    averaged = indicators.with_columns(index=index).with_columns(
        adx=exponential_average(pl.col("index"), 1 / n, pl.col("index").rolling_mean(n), 2 * n - 1)
    )
    return averaged.select("ts_close", "adx", "plus_di", "minus_di")


@feature(params={"n": 20}, warmup=lambda n: n, outputs={"obv": "count"})
def obv(bars: pl.LazyFrame, n: BarCount) -> pl.Expr:
    """On-balance volume over the last `n` bars: the volume of those that closed above the close
    before them less the volume of those that closed below it, which is TA-Lib's OBV less its
    value `n` bars before. TA-Lib's runs from the first bar, so its level depends on where the
    data starts, which the feature cache and the leak detector refuse (your choice, D-75)."""
    signed_volume = pl.col("volume").cast(pl.Int64) * pl.col("close").diff().sign()
    return signed_volume.rolling_sum(n)
