"""Where a session-aware indicator starts, and what it remembers (step 3.6, D-71, D-78): the
session's open, which every trade date and bar take, or a local time of day in the product's time
zone on the trade date's own day, such as 08:30 Chicago for the cash open, as the execution
template's time rules read a local time (F-TIM-01, D-53); the bars a Boolean column flags, as a
roll's first; the running number of each row's session, which bounds a memory to whole sessions
from any start; and the price a bar weighs in a VWAP."""

from datetime import time

import polars as pl


def session_start(anchor: str | None, time_zone: str) -> pl.Expr:
    """The instant an indicator starts from on each row's trade date, in nanoseconds since the
    Unix epoch, UTC: the session's open, its grid's first bucket, where `anchor` is None; else the
    local time of day `anchor`, `HH:MM`, in `time_zone` on the trade date's own day, after the
    close for an evening time, which no bar of the session reaches. A local time a clock change
    skips or repeats that day is refused, as F-TIM-05 refuses one."""
    if anchor is None:
        return pl.col("ts_open").first().over("trade_date")
    local = pl.col("trade_date").dt.combine(time.fromisoformat(anchor), time_unit="ns")
    zoned = local.dt.replace_time_zone(time_zone, ambiguous="raise", non_existent="raise")
    return zoned.cast(pl.Int64)


def session_number() -> pl.Expr:
    """The number of each row's session among the frame's, 1 on its first trade date, counted as
    the rows go, so that the sessions between two rows are the same from any start."""
    trade_date = pl.col("trade_date")
    return (trade_date != trade_date.shift(1)).fill_null(True).cum_sum()


def flagged(bars: pl.LazyFrame, flag: str) -> pl.Expr:
    """The Boolean column `flag` of `bars`, a null read as false; a column that is not Boolean,
    or none, is refused."""
    schema = bars.collect_schema()
    if schema.get(flag) != pl.Boolean:
        got = "no such column" if flag not in schema else f"a column of {schema[flag]}"
        raise ValueError(
            f"Expected flag to name a Boolean column of the bars, such as roll_flag, got {flag}: "
            f"{got}."
        )
    return pl.col(flag).fill_null(False)


def within_sessions(flags: pl.Expr, sessions: int) -> pl.Expr:
    """Whether each row lies in the session of the last bar `flags` marks, or in the `sessions` -
    1 sessions after it, which bounds what an indicator since an event remembers, so that a later
    start, which holds those sessions whole once its warm-up of `sessions` - 1 sessions has passed,
    gives the same values; false before the first. The session numbers are the frame's, never a
    partition's, which a window function would count apart."""
    number = session_number()
    flagged_in = pl.when(flags).then(number).forward_fill()
    return flagged_in.is_not_null() & (number - flagged_in < sessions)


def bar_price() -> pl.Expr:
    """The price a bar weighs in a VWAP: its own vwap where the data gives one, else its typical
    price, the mean of its high, low, and close, as charting platforms weigh a bar without one."""
    typical = (pl.col("high") + pl.col("low") + pl.col("close")).cast(pl.Float64) / 3
    return pl.col("vwap").cast(pl.Float64).fill_null(typical)
