"""A dataset's offset from its calendar (step 1.10, `02-engine-and-data.md` §1.8): the time
by which all its records run late or early, as an import read in the wrong time zone or with
the wrong bar stamping gives. Whole or half hours show when moving the records back by them
puts inside the sessions most of the records outside them; one bar shows when most sessions
hold a bar just past an edge, one opening at the close (a file that stamps each bar's close,
read as its open) or one in the break closing at the next open (the opposite mistake). The
calendar check (`fefat.market.calendar_check`) reports it beside its mismatches.

    records_offset(dataset, bars.lazy(), sessions)
"""

from enum import StrEnum

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.layout import Dataset
from fefat.market.schema import BarSchemaName, FrozenModel, TimeUnit

_SECOND = 1_000_000_000
_MINUTE = 60 * _SECOND
_HALF_HOUR = 30 * _MINUTE
_ZONE_OFFSETS = tuple(step * _HALF_HOUR for step in range(-28, 29) if step != 0)
"""The offsets a file read in the wrong time zone shows: half hours, up to 14 hours either way."""
_OFFSET_SAMPLE = 50_000
"""At most this many of a dataset's minutes with records are tried at each offset."""
_SIGNIFICANT_SHARE = 0.01
"""The share of a dataset's minutes that must lie outside every session for an offset to be
looked for: a correct file has a few, such as prints received in the break after a close."""


class OffsetCause(StrEnum):
    """What a dataset's offset points at: hours at the time zone the file's times are in, one
    bar at the side of the bar its timestamps mark, and a half hour or an hour of bars as long
    as one at either."""

    TIME_ZONE = "time-zone"
    BAR_STAMPING = "bar-stamping"
    TIME_ZONE_OR_BAR_STAMPING = "time-zone-or-bar-stamping"


_CHECK_OF_CAUSE = {
    OffsetCause.TIME_ZONE: "check the time zone of the file's times",
    OffsetCause.BAR_STAMPING: "check whether the file stamps each bar at its open or its close",
    OffsetCause.TIME_ZONE_OR_BAR_STAMPING: (
        "check the time zone of the file's times, and whether it stamps each bar at its open "
        "or its close"
    ),
}


class CalendarOffset(FrozenModel):
    """The time by which a dataset's records run late against its calendar, in nanoseconds,
    early when negative, and what it points at."""

    dataset: Dataset
    nanoseconds: int
    cause: OffsetCause

    def describe(self) -> str:
        """One line: the dataset, how far its records run late or early, and what to check."""
        direction = "late" if self.nanoseconds > 0 else "early"
        size = duration_text(abs(self.nanoseconds))
        heading = f"{self.dataset.relative_folder()} offset: its records run {size} {direction}"
        return f"{heading} against the calendar; {_CHECK_OF_CAUSE[self.cause]}"


def duration_text(nanoseconds: int) -> str:
    """A positive duration in hours, minutes, and seconds, such as `5 hours 30 minutes`."""
    hours, rest = divmod(nanoseconds // _SECOND, 3_600)
    minutes, seconds = divmod(rest, 60)
    parts = (("hour", hours), ("minute", minutes), ("second", seconds))
    return " ".join(f"{count} {unit}{'' if count == 1 else 's'}" for unit, count in parts if count)


def records_offset(
    dataset: Dataset, records: pl.LazyFrame, sessions: SessionTable
) -> CalendarOffset | None:
    """The time by which a dataset's records, dated by `trade_date`, run late or early against
    `sessions`, or None where nothing shows one: whole or half hours first, then one bar."""
    schema_name = dataset.schema_name
    timeframe = schema_name.timeframe if isinstance(schema_name, BarSchemaName) else None
    clock = "ts_recv" if timeframe is None else "ts_open"
    width = None if timeframe is None else timeframe.nominal_nanoseconds()
    zone = _zone_offset(records.select(clock).collect().get_column(clock), sessions)
    if zone is not None:
        cause = (
            OffsetCause.TIME_ZONE_OR_BAR_STAMPING if abs(zone) == width else OffsetCause.TIME_ZONE
        )
        return CalendarOffset(dataset=dataset, nanoseconds=zone, cause=cause)
    if width is None or timeframe is None or timeframe.unit is TimeUnit.DAY:
        return None
    stamping = _stamping_offset(records, sessions, width)
    if stamping is None:
        return None
    cause = (
        OffsetCause.TIME_ZONE_OR_BAR_STAMPING
        if width % _HALF_HOUR == 0
        else OffsetCause.BAR_STAMPING
    )
    return CalendarOffset(dataset=dataset, nanoseconds=stamping, cause=cause)


def _zone_offset(instants: pl.Series, sessions: SessionTable) -> int | None:
    """The half hours by which the instants run late, when at least `_SIGNIFICANT_SHARE` of
    their minutes lie outside every session and moving them back by it leaves under half of
    those outside; the smallest such offset that leaves fewest outside."""
    minutes = (instants // _MINUTE * _MINUTE).unique().sort()
    if minutes.len() > _OFFSET_SAMPLE:
        minutes = minutes.gather_every(minutes.len() // _OFFSET_SAMPLE + 1)
    outside = {offset: _outside(minutes - offset, sessions) for offset in (0, *_ZONE_OFFSETS)}
    if outside[0] == 0 or outside[0] < _SIGNIFICANT_SHARE * minutes.len():
        return None
    best = min(_ZONE_OFFSETS, key=lambda offset: (outside[offset], abs(offset)))
    return best if outside[best] * 2 < outside[0] else None


def _outside(instants: pl.Series, sessions: SessionTable) -> int:
    """How many of the instants lie outside every session of the table, or beyond its span."""
    first_open, last_close = sessions.span()
    kept = instants.filter(instants.is_between(first_open, last_close, closed="left"))
    dated = sessions.assign_trade_dates_or_previous(kept.to_frame("instant"), "instant")
    inside = int(dated.get_column("in_session").sum())
    return instants.len() - inside


def _stamping_offset(bars: pl.LazyFrame, sessions: SessionTable, width: int) -> int | None:
    """One bar late, when at least half the sessions with bars hold one opening at the close,
    as a file that stamps each bar's close read as its open gives; one bar early, when at least
    half hold one in the break closing at the next open, as the opposite mistake gives."""
    first, last = (
        bars.select(first=pl.col("trade_date").min(), last=pl.col("trade_date").max())
        .collect()
        .row(0)
    )
    bounds = sessions.between_with_next_opens(first, last).select(
        "trade_date", "next_open", session_close="close"
    )
    in_the_break = pl.col("ts_open") >= pl.col("session_close")
    edges = (
        bars.select("trade_date", "ts_open", "ts_close")
        .join(bounds.lazy(), on="trade_date")
        .group_by("trade_date")
        .agg(
            late=(pl.col("ts_open") == pl.col("session_close")).any(),
            early=(in_the_break & (pl.col("ts_close") == pl.col("next_open"))).any(),
        )
        .collect()
    )
    late, early = (int(edges.get_column(column).sum()) for column in ("late", "early"))
    if late > early and late * 2 >= edges.height:
        return width
    if early > late and early * 2 >= edges.height:
        return -width
    return None
