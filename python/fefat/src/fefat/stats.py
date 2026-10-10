"""Statistics over Polars series, computed by the Rust engine."""

import fefat_engine
import polars as pl

__all__ = ["max_drawdown"]


def max_drawdown(values: pl.Series) -> int:
    """The largest fall of the cumulative sum of `values` below its highest point so far.

    The sum starts at 0, which counts as the first peak: a series that only falls has a
    drawdown equal to its total loss, and an empty series gives 0. The engine reads the
    series' memory in place, without a copy. It refuses a series that is not int64
    (TypeError) or holds nulls (ValueError), and a sum beyond int64 (OverflowError).
    """
    return fefat_engine.max_drawdown_arrow(values)
