"""The session's own levels and clock (step 3.6, D-71, D-78): its opening range, its high and low
so far, the high, low, and close of the session before, the time since its open, and the bars since
an event. A session is a trade date's rows of the grid, whose buckets leave halts out (D-43), and
the session before is the trade date before it in the session table, which the grid holds whole,
never the rows before. A bucket without trades holds the close before it, which no trade in it
made, so the levels read the bars that traded alone."""

from typing import Annotated

import polars as pl
from pydantic import Field

from fefat.features.definition import SessionCount, feature
from fefat.indicators.anchors import flagged, session_start, within_sessions
from fefat.market.calendar_definition import LocalTime, TimeZoneName

MinuteCount = Annotated[int, Field(ge=1)]
"""A number of minutes, at least one, as an opening range's window."""


@feature(
    params={"minutes": 30, "anchor": None, "time_zone": "America/Chicago"},
    outputs={"range_high": "price", "range_low": "price", "range_width": "price_distance"},
)
def opening_range(
    bars: pl.LazyFrame, minutes: MinuteCount, anchor: LocalTime | None, time_zone: TimeZoneName
) -> dict[str, pl.Expr]:
    """The high, the low, and the width of the bars that traded wholly inside the `minutes` from
    the session's open, or from the local time of day `anchor` in `time_zone` on the trade date's
    own day, given from the first bar opening at or after the window's end, so once the window has
    closed, and null before it and where no bar traded inside it."""
    start = session_start(anchor, time_zone)
    end = start + minutes * 60_000_000_000
    inside = (pl.col("ts_open") >= start) & (pl.col("ts_close") <= end) & (pl.col("volume") > 0)
    high = pl.when(inside).then(pl.col("high")).cum_max().forward_fill().over("trade_date")
    low = pl.when(inside).then(pl.col("low")).cum_min().forward_fill().over("trade_date")
    closed = pl.col("ts_open") >= end
    return {
        "range_high": pl.when(closed).then(high),
        "range_low": pl.when(closed).then(low),
        "range_width": pl.when(closed).then(high - low),
    }


@feature(
    warmup_sessions=1,
    outputs={"previous_high": "price", "previous_low": "price", "previous_close": "price"},
)
def previous_session(bars: pl.LazyFrame) -> pl.LazyFrame:
    """The high and the low of the bars that traded in the session before, and its close, its
    last bar's, after a session of warm-up."""
    traded = pl.col("volume") > 0
    sessions = bars.group_by("trade_date").agg(
        previous_high=pl.col("high").filter(traded).max(),
        previous_low=pl.col("low").filter(traded).min(),
        previous_close=pl.col("close").last(),
    )
    levels = ["previous_high", "previous_low", "previous_close"]
    shifted = sessions.sort("trade_date").with_columns(pl.col(levels).shift(1))
    joined = bars.join(shifted, on="trade_date", how="left", maintain_order="left")
    return joined.select("ts_close", *levels)


@feature(outputs={"session_high": "price", "session_low": "price"})
def session_high_low(bars: pl.LazyFrame) -> dict[str, pl.Expr]:
    """The highest high and the lowest low of the session's bars that traded so far, null before
    its first."""
    traded = pl.when(pl.col("volume") > 0)
    return {
        "session_high": traded.then(pl.col("high")).cum_max().forward_fill().over("trade_date"),
        "session_low": traded.then(pl.col("low")).cum_min().forward_fill().over("trade_date"),
    }


@feature(outputs={"bars_since_open": "count", "minutes_since_open": "other"})
def time_since_open(bars: pl.LazyFrame) -> dict[str, pl.Expr]:
    """The bars of the session's grid closed by each row's close, 1 on its first, and the minutes
    of the grid's time since its open by then, its halts left out (D-43)."""
    lasted = (pl.col("ts_close") - pl.col("ts_open")).cum_sum().over("trade_date")
    return {
        "bars_since_open": pl.col("ts_close").cum_count().over("trade_date"),
        "minutes_since_open": lasted / 60_000_000_000,
    }


@feature(
    params={"sessions": 1},
    warmup_sessions=lambda sessions: sessions - 1,
    outputs={"bars_since": "count"},
)
def bars_since(bars: pl.LazyFrame, flag: str, sessions: SessionCount) -> pl.Expr:
    """The bars of the grid since the last bar on which the Boolean column `flag` of the bars is
    true, 0 on it: null before the first such bar, and once the last lies further back than this
    session and the `sessions` - 1 before it, which bound what it remembers
    (`anchors.within_sessions`)."""
    flags = flagged(bars, flag)
    since = pl.col("ts_close").cum_count().over(flags.cum_sum()) - 1
    return pl.when(within_sessions(flags, sessions)).then(since)
