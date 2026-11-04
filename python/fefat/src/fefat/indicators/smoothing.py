"""What the indicators share (step 3.5): an exponential average seeded where TA-Lib seeds it, and
each bar's true range. An exponential average remembers its first bars, a little less with each
bar, so an indicator built on one declares 25 times its period as its warm-up, after which those
bars weigh less than 1e-11, well inside the 1e-9 within which the feature cache and the leak
detector take two evaluations as equal (D-73, D-74, D-75)."""

import polars as pl


def exponential_average(values: pl.Expr, alpha: float, seed: pl.Expr, first: int) -> pl.Expr:
    """`values` averaged as TA-Lib averages them: null before the row `first`, `seed` there, and
    from the next row on each value weighing `alpha` against the average before it. TA-Lib's
    seed is a simple average of the first values, where Polars' `ewm_mean` would start from the
    first value alone; a null value after `first` gives a null on its row and leaves the average
    to the rows after it."""
    row = pl.int_range(pl.len())
    seeded = pl.when(row == first).then(seed).when(row > first).then(values)
    return seeded.cast(pl.Float64).ewm_mean(alpha=alpha, adjust=False, ignore_nulls=True)


def true_ranges() -> pl.Expr:
    """Each bar's true range, its high less its low, widened to the close before it, as TA-Lib's
    TRANGE: null on the first bar, which has no close before it."""
    previous = pl.col("close").shift(1)
    widened = pl.max_horizontal("high", previous) - pl.min_horizontal("low", previous)
    return pl.when(previous.is_not_null()).then(widened)
