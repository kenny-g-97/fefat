"""A dataset's offset from its calendar (step 1.10, `02-engine-and-data.md` §1.8): the time
by which its records run late or early, as an import read in the wrong time zone or with the
wrong bar stamping gives. Whole or half hours show when moving the records back by them puts
inside the sessions most of the records outside them, over the whole dataset, or over its part
on one side of a change of the calendar's offset from UTC, as times kept in standard time across
a daylight-saving change give, where that part, moved back, spans a whole session, or where no
bar of it closes at an open from the break before it. One bar early shows when a session beside
a bar closing at the next open, the session that bar opens or the one before it, holds no bar in
its last bucket and one in the bucket before, as a file that stamps each bar's open, read as its
close, gives, or when at least half the sessions with bars have such a bar before their open;
one bar late, when most sessions hold a bar opening at the close and open their first a bar
after the open (the opposite mistake), since a correct file may hold a straggler at the close,
or start inside a session. A bar closing at an open otherwise is a bar in a break, the edge of a
stretch a platform stamped early (`fefat.market.calendar_breaks`, ADR-0022, step 5.15).
The calendar check (`fefat.market.calendar_check`) reports it beside its mismatches.

An offset shows only where records reach the edges of sessions that a break bounds:
`timing_checked` tells whether moving the records by an hour, or a bar, would show one, which
records of regular hours only, thin ones, or a calendar without breaks never do.

    records_offset(dataset, bars.lazy(), sessions)
    timing_checked(dataset, bars, sessions)
"""

from datetime import date
from enum import StrEnum

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.calendar_breaks import (
    ENDS_A_BAR_EARLY,
    REACHES_THE_NEXT_OPEN,
    bars_with_their_sessions,
    session_edges,
)
from fefat.market.layout import Dataset
from fefat.market.schema import BarSchemaName, FrozenModel, Timeframe, TimeUnit

_SECOND = 1_000_000_000
_MINUTE = 60 * _SECOND
_HALF_HOUR = 30 * _MINUTE
_HOUR = 60 * _MINUTE
_ZONE_OFFSETS = tuple(step * _HALF_HOUR for step in range(-28, 29) if step != 0)
"""The offsets a file read in the wrong time zone shows: half hours, up to 14 hours either way."""
_OFFSET_SAMPLE = 50_000
"""At most this many of a dataset's minutes with records are tried at each offset."""
_SIGNIFICANT_SHARE = 0.01
"""The share of a dataset's minutes that must lie outside every session for an offset to be
looked for: a correct file has a few, such as prints received in the break after a close."""
_SIGNIFICANT_MINUTES = 10
"""How many minutes must lie outside every session for an offset to be looked for, so that
a straggler after a close in a small part of a file, which any move into the session would
fix, shows none."""
_WHOLE_SESSION_MARGIN = _HALF_HOUR
"""How far inside a session's open and close the first and last minute of a part of a file may
lie for the part to span that session whole (`_part_runs_off`)."""
TIMING_UNCHECKED = (
    "the calendar could not check the file's time zone and bar stamping: its records moved by "
    "an hour or a bar would still fit their sessions, as records of regular hours only, thin "
    "ones, or a calendar without breaks give, so compare a few bars with the platform's chart"
)
"""The warning of an import whose timing the calendar check cannot test (`timing_checked`)."""


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
    """The time by which a dataset's records of the trade dates from `first_trade_date` to
    `last_trade_date` run late against its calendar, in nanoseconds, early when negative, and
    what it points at."""

    dataset: Dataset
    nanoseconds: int
    cause: OffsetCause
    first_trade_date: date
    last_trade_date: date

    def describe(self) -> str:
        """One line: the dataset, how far its records run late or early, on which trade dates,
        and what to check."""
        direction = "late" if self.nanoseconds > 0 else "early"
        size = duration_text(abs(self.nanoseconds))
        dates = (
            f"the trade date {self.first_trade_date}"
            if self.first_trade_date == self.last_trade_date
            else f"the trade dates {self.first_trade_date} to {self.last_trade_date}"
        )
        heading = f"{self.dataset.relative_folder()} offset: its records run {size} {direction}"
        return f"{heading} against the calendar on {dates}; {_CHECK_OF_CAUSE[self.cause]}"


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
    `sessions`, or None where nothing shows one: whole or half hours first, of all the records
    or of those on one side of a change of the calendar's offset from UTC, then one bar."""
    timeframe = _timeframe(dataset)
    clock = "ts_recv" if timeframe is None else "ts_open"
    minutes = (
        records.select((pl.col(clock) // _MINUTE * _MINUTE).unique().sort())
        .collect(engine="streaming")
        .get_column(clock)
    )
    width = None if timeframe is None else timeframe.nominal_nanoseconds()
    intraday = timeframe is not None and timeframe.unit is not TimeUnit.DAY
    hours = _hours_offset(minutes, sessions, records if intraday else None)
    if hours is not None:
        zone, part = hours
        cause = (
            OffsetCause.TIME_ZONE_OR_BAR_STAMPING if abs(zone) == width else OffsetCause.TIME_ZONE
        )
        return _offset(dataset, part, zone, cause, sessions)
    if width is None or not intraday:
        return None
    stamping = _stamping_offset(records, sessions, width)
    if stamping is None:
        return None
    cause = (
        OffsetCause.TIME_ZONE_OR_BAR_STAMPING
        if width % _HALF_HOUR == 0
        else OffsetCause.BAR_STAMPING
    )
    return _offset(dataset, minutes, stamping, cause, sessions)


def timing_checked(dataset: Dataset, records: pl.DataFrame, sessions: SessionTable) -> bool:
    """Whether the calendar check would show the records run an hour late or early, and bars
    one bar: moving them by such a time gives an offset (`records_offset`). Daily bars are
    dated by the date they name, which no time zone or stamping moves."""
    timeframe = _timeframe(dataset)
    if records.is_empty() or (timeframe is not None and timeframe.unit is TimeUnit.DAY):
        return True
    clocks = ("ts_recv",) if timeframe is None else ("ts_open", "ts_close")
    steps = {_HOUR} if timeframe is None else {_HOUR, timeframe.nominal_nanoseconds()}
    return all(
        records_offset(dataset, _moved(records, clocks, shift, sessions).lazy(), sessions)
        is not None
        for step in sorted(steps)
        for shift in (step, -step)
    )


def _timeframe(dataset: Dataset) -> Timeframe | None:
    schema_name = dataset.schema_name
    return schema_name.timeframe if isinstance(schema_name, BarSchemaName) else None


def _hours_offset(
    minutes: pl.Series, sessions: SessionTable, bars: pl.LazyFrame | None
) -> tuple[int, pl.Series] | None:
    """The half hours by which the minutes run late, with the minutes that run so: all of them,
    or those on one side of a change of the calendar's offset from UTC where, moved back by
    them, they span a whole session (`_part_runs_off`), or where no bar of `bars`, a file's
    intraday bars, among them closes at an open from the break before it (`_reaches_an_open`),
    since a few hours of a session after a clock change read as far off beside such a bar, the
    edge of a stretch a platform stamped early (ADR-0022); none where neither shows."""
    zone = _zone_offset(minutes, sessions)
    if zone is not None:
        return zone, minutes
    for part in _parts_by_utc_offset(minutes, sessions):
        zone = _zone_offset(part, sessions)
        if zone is None:
            continue
        if _part_runs_off(part - zone, sessions) or not _reaches_an_open(part, bars, sessions):
            return zone, part
    return None


def _reaches_an_open(part: pl.Series, bars: pl.LazyFrame | None, sessions: SessionTable) -> bool:
    """Whether a bar of `bars` at one of the part's minutes opens after its session's close and
    closes at the next session's open (`REACHES_THE_NEXT_OPEN`); never for ticks and daily bars,
    given as None."""
    bounded = None if bars is None else bars_with_their_sessions(bars, sessions)
    if bounded is None:
        return False
    reaching = (
        bounded.filter(REACHES_THE_NEXT_OPEN)
        .select(pl.col("ts_open") // _MINUTE * _MINUTE)
        .collect(engine="streaming")
        .get_column("ts_open")
    )
    return bool(part.is_in(reaching.implode()).any())


def _part_runs_off(moved: pl.Series, sessions: SessionTable) -> bool:
    """Whether a part of a file, its minutes moved back by its hours, spans a session whole: its
    first minute under `_WHOLE_SESSION_MARGIN` after the session's open, and its last within it
    of the session's close. A part with minutes in sessions of three trade dates or more spans
    the middle one, so thin sessions count while a few hours after a clock change do not.
    Minutes beyond the session table are left out."""
    first_open, last_close = sessions.span()
    kept = moved.filter(moved.is_between(first_open, last_close, closed="left"))
    if kept.is_empty():
        return False
    first, last = kept.min(), kept.max()
    reach = pl.DataFrame({"instant": [first, last]}, schema={"instant": pl.Int64})
    first_date, last_date = _first_and_last(
        sessions.assign_trade_dates_or_previous(reach, "instant")
    )
    spanned = sessions.between(first_date, last_date).filter(
        (pl.col("open") + _WHOLE_SESSION_MARGIN > first)
        & (pl.col("close") - _WHOLE_SESSION_MARGIN <= last)
    )
    return not spanned.is_empty()


def _zone_offset(minutes: pl.Series, sessions: SessionTable) -> int | None:
    """The half hours by which the minutes run late, when at least `_SIGNIFICANT_MINUTES`
    and `_SIGNIFICANT_SHARE` of them lie outside every session and moving them back by it
    leaves under half of those outside; the smallest such offset that leaves fewest outside."""
    sampled = minutes.gather_every(minutes.len() // _OFFSET_SAMPLE + 1)
    outside = _outside(sampled, sessions)
    if outside < _SIGNIFICANT_MINUTES or outside < _SIGNIFICANT_SHARE * sampled.len():
        return None
    moved = {offset: _outside(sampled - offset, sessions) for offset in _ZONE_OFFSETS}
    best = min(_ZONE_OFFSETS, key=lambda offset: (moved[offset], abs(offset)))
    return best if moved[best] * 2 < outside else None


def _parts_by_utc_offset(minutes: pl.Series, sessions: SessionTable) -> list[pl.Series]:
    """The minutes split where the calendar's time zone changes its offset from UTC, each part
    running from just after the last close of the part before it; none where they keep to one
    offset."""
    first_open, last_close = sessions.span()
    inside = minutes.filter(minutes.is_between(first_open, last_close, closed="left"))
    if inside.is_empty():
        return []
    span = pl.DataFrame({"instant": [inside.min(), inside.max()]}, schema={"instant": pl.Int64})
    first, last = _first_and_last(sessions.assign_trade_dates_or_previous(span, "instant"))
    local_open = (
        pl.from_epoch("open", time_unit="ns")
        .dt.replace_time_zone("UTC")
        .dt.convert_time_zone(sessions.time_zone())
    )
    utc_offset = local_open.dt.base_utc_offset() + local_open.dt.dst_offset()
    ends = (
        sessions.between(first, last)
        .group_by(utc_offset.rle_id().alias("part"), maintain_order=True)
        .agg(pl.col("close").max())
        .get_column("close")
    )
    if ends.len() < 2:
        return []
    part = ends.search_sorted(minutes, side="left").clip(upper_bound=ends.len() - 1)
    return [minutes.filter(part == index) for index in range(ends.len())]


def _outside(instants: pl.Series, sessions: SessionTable) -> int:
    """How many of the instants lie outside every session of the table, or beyond its span."""
    first_open, last_close = sessions.span()
    kept = instants.filter(instants.is_between(first_open, last_close, closed="left"))
    dated = sessions.assign_trade_dates_or_previous(kept.to_frame("instant"), "instant")
    inside = int(dated.get_column("in_session").sum())
    return instants.len() - inside


def _stamping_offset(bars: pl.LazyFrame, sessions: SessionTable, width: int) -> int | None:
    """One bar early, then one bar late, as the edges of the bars' sessions show them
    (`_session_edges`, `_runs_a_bar_early`, `_runs_a_bar_late`); none otherwise."""
    edges = _session_edges(bars, sessions, width)
    if edges is None:
        return None
    if _runs_a_bar_early(edges):
        return -width
    if _runs_a_bar_late(edges):
        return width
    return None


def _session_edges(bars: pl.LazyFrame, sessions: SessionTable, width: int) -> pl.DataFrame | None:
    """A row per trade date of `bars`, `width` long, with the edges of its session
    (`fefat.market.calendar_breaks.session_edges`); none without bars."""
    bounded = bars_with_their_sessions(bars, sessions)
    return None if bounded is None else session_edges(bounded, width)


def _runs_a_bar_early(edges: pl.DataFrame) -> bool:
    """Whether a session beside a bar closing at the next open, the session that bar opens or
    the one before it, holds no bar in its last bucket and one in the bucket before, as a file
    that stamps each bar's open, read as its close, gives, or at least half the sessions with
    bars have such a bar before their open; a bar closing at an open otherwise is a bar in a
    break (ADR-0022), since nothing prints in the minute before an open."""
    reached = edges.filter("reaches_the_next_open").get_column("next_open")
    with_bars = edges.filter("inside")
    headed = pl.col("session_open").is_in(reached.implode())
    beside_the_bar = headed | pl.col("reaches_the_next_open")
    if not with_bars.filter(beside_the_bar & ENDS_A_BAR_EARLY).is_empty():
        return True
    headed_sessions = with_bars.filter(headed).height
    return headed_sessions > 0 and headed_sessions * 2 >= with_bars.height


def _runs_a_bar_late(edges: pl.DataFrame) -> bool:
    """Whether at least half the trade dates with bars hold one opening at the close and open
    their first one bar after the open, as a file that stamps each bar's close, read as its
    open, gives, since a correct file may hold a straggler at the close, or start inside a
    session."""
    late = int(edges.get_column("late").sum())
    return late > 0 and late * 2 >= edges.height


def _offset(
    dataset: Dataset,
    minutes: pl.Series,
    nanoseconds: int,
    cause: OffsetCause,
    sessions: SessionTable,
) -> CalendarOffset:
    """The offset of the records at `minutes`, on the trade dates of the sessions that moving
    them back by it puts them in."""
    moved = minutes - nanoseconds
    first_open, last_close = sessions.span()
    kept = moved.filter(moved.is_between(first_open, last_close, closed="left"))
    dated = sessions.assign_trade_dates_or_previous(kept.to_frame("instant"), "instant")
    in_session = dated.filter("in_session")
    if in_session.is_empty():
        raise ValueError(
            f"Expected the records moved back by {duration_text(abs(nanoseconds))} to land in "
            f"sessions, got none of {dataset.relative_folder()}: the offset cannot be described."
        )
    first, last = _first_and_last(in_session)
    return CalendarOffset(
        dataset=dataset,
        nanoseconds=nanoseconds,
        cause=cause,
        first_trade_date=first,
        last_trade_date=last,
    )


def _first_and_last(dated: pl.DataFrame) -> tuple[date, date]:
    """The first and last of the trade dates of `dated`."""
    first, last = dated.select(
        first=pl.col("trade_date").min(), last=pl.col("trade_date").max()
    ).row(0)
    return first, last


def _moved(
    records: pl.DataFrame, clocks: tuple[str, ...], nanoseconds: int, sessions: SessionTable
) -> pl.DataFrame:
    """The records' clocks moved later by `nanoseconds` and dated again by the first, as an
    import dates them; those the move takes beyond the session table are left out."""
    first_open, last_close = sessions.span()
    moved = records.select(pl.col(name) + nanoseconds for name in clocks)
    kept = moved.filter(pl.col(clocks[0]).is_between(first_open, last_close, closed="left"))
    return sessions.assign_trade_dates_or_previous(kept, clocks[0]).drop("in_session")
