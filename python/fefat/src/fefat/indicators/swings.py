"""Swing highs and lows confirmed after `n` bars (step 3.6): a bar's high is a swing high when it
stands strictly above the `n` highs before it and the `n` after it, which only the `n`-th bar
after it can show, so the swing is flagged on that bar, never on its own, and no later bar takes
it back: the detector does not repaint, as a pivot drawn on the bar itself does, which reads the
bars after it (D-12). A swing low is the same below the lows."""

import polars as pl

from fefat.features.definition import BarCount, feature


@feature(
    params={"n": 5},
    warmup=lambda n: 2 * n,
    outputs={
        "swing_high": "flag",
        "swing_low": "flag",
        "swing_high_price": "price",
        "swing_low_price": "price",
    },
)
def swings(bars: pl.LazyFrame, n: BarCount) -> dict[str, pl.Expr]:
    """Whether the bar `n` bars back is a swing high, or a swing low, confirmed on this bar, and
    its high or its low on the bar that confirms it, null on the others; a strategy that wants
    the last swing's level carries it forward itself."""
    high, low = pl.col("high"), pl.col("low")
    peak, trough = high.shift(n), low.shift(n)
    is_high = (peak > high.shift(n + 1).rolling_max(n)) & (peak > high.rolling_max(n))
    is_low = (trough < low.shift(n + 1).rolling_min(n)) & (trough < low.rolling_min(n))
    return {
        "swing_high": is_high,
        "swing_low": is_low,
        "swing_high_price": pl.when(is_high).then(peak),
        "swing_low_price": pl.when(is_low).then(trough),
    }
