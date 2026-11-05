"""Volume against its own (step 3.6, D-71, D-78): relative volume, a bar's volume against the mean
at the same local time of day over the sessions before it, and cumulative delta, the volume
bought less the volume sold by aggressors, from the sides of the prints (the trades input,
`fefat.market.aggressor`)."""

import polars as pl

from fefat.features.definition import SessionCount, feature
from fefat.features.inputs import TradesInput
from fefat.indicators.anchors import session_number
from fefat.market.calendar_definition import TimeZoneName


@feature(
    params={"sessions": 20, "time_zone": "America/Chicago"},
    warmup_sessions=lambda sessions: sessions,
    outputs={"relative_volume": "ratio"},
)
def relative_volume(
    bars: pl.LazyFrame, sessions: SessionCount, time_zone: TimeZoneName
) -> pl.LazyFrame:
    """A bar's volume over the mean volume of the bars opening at the same local time of day in
    `time_zone` on the `sessions` trade dates before its own, a session without such a bar, as an
    early close's, left out: never its own session or a later one. Null where that mean is 0 or
    no session before holds the time. The sessions are numbered over the frame before the bars
    are grouped by their time of day, inside which they would count that time's bars instead."""
    local = pl.col("ts_open").cast(pl.Datetime("ns", "UTC")).dt.convert_time_zone(time_zone)
    numbered = bars.with_columns(session=session_number(), clock=local.dt.time())
    volume = pl.col("volume").cast(pl.Float64)
    before = volume.rolling_mean_by("session", window_size=f"{sessions}i", closed="left")
    usual = before.over("clock")
    return numbered.select("ts_close", relative_volume=pl.when(usual > 0).then(volume / usual))


@feature(inputs=[TradesInput()], outputs={"delta": "count", "cumulative_delta": "count"})
def cumulative_delta(bars: pl.LazyFrame) -> dict[str, pl.Expr]:
    """The volume bought less the volume sold by aggressors in each bar, `delta`, and in the
    session so far, `cumulative_delta`, in contracts: from the session's first print with a side,
    the prints of no side, as an opening auction's, left out; null before it, so through a session
    whose prints carry no side, as IBKR's, never zero, and on a trade date without prints, where
    no volume is known."""
    bought, sold = pl.col("buy_volume"), pl.col("sell_volume")
    sided = (bought + sold > 0).cum_max().over("trade_date")
    delta = pl.when(sided).then(bought - sold)
    return {"delta": delta, "cumulative_delta": delta.cum_sum().over("trade_date")}
