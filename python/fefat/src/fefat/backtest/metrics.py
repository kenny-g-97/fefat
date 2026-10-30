"""A run's metrics (step 2.11, `02` §7), worked out by the Rust engine's `fefat-metrics`."""

import fefat_engine
import polars as pl


def running_drawdown(equity: pl.Series) -> pl.Series:
    """How far each value of `equity`, an account's equity in order, lies below the highest value
    before it or at it, in its units: zero at each new peak, and at the first value. The engine
    reads the series in place, a slice without the values around it, and refuses one that is not
    int64 (TypeError) or holds nulls (ValueError), and a fall beyond int64 (OverflowError)."""
    return pl.Series(equity.name, fefat_engine.running_drawdown(equity), dtype=pl.Int64)
