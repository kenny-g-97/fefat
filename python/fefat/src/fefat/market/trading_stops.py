"""The stops of trading of a session (`docs/spec/fill-semantics.md` §20, F-TIM-03), from the session
table: each holiday halt, from which trading resumes at the calendar's regular open (D-41), and the
close, from which it resumes at the next session's open; a daily halt, which every session of its
era holds, is none. A stop whose break holds a day of the week on which the calendar has no trade
date is a weekend. The execution template's time rules (`fefat.reference.time_rules`) and the leak
detector's cuts (`fefat.features.cuts`) read them.

    trading_stops(sessions, date(2026, 3, 6))  # Friday's close, until Sunday's open: a weekend
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.calendar_definition import SessionHours


@dataclass(frozen=True, slots=True)
class TradingStop:
    """A stop of trading (§20): from `start` until trading resumes at `resumes`, in nanoseconds
    since the Unix epoch, UTC; over a weekend when its break holds a day of the week on which the
    calendar has no trade date."""

    start: int
    resumes: int
    weekend: bool


def trading_stops(sessions: SessionTable, trade_date: date) -> tuple[TradingStop, ...]:
    """The stops of trading of `trade_date`'s session, in order: each holiday halt, from which
    trading resumes at the calendar's regular open (D-41), and the close, from which it resumes
    at the next session's open; a daily halt, which every session of its era holds, is none."""
    session, hours = sessions.session(trade_date), sessions.hours()
    breaks = [
        (halt.start, halt.end)
        for halt in session.halts
        if _local(halt.end, hours.time_zone).time() == hours.opens_at
    ]
    breaks.append((session.close, sessions.following(trade_date).open))
    return tuple(
        TradingStop(start, resumes, _holds_a_day_off(start, resumes, hours))
        for start, resumes in breaks
    )


def _holds_a_day_off(start: int, resumes: int, hours: SessionHours) -> bool:
    """Whether a break from `start` to `resumes` holds a whole local day on which the calendar
    has no trade date, such as a Saturday for CME: a weekend."""
    first, last = (_local(instant, hours.time_zone).date() for instant in (start, resumes))
    held = (first + timedelta(days=offset) for offset in range(1, (last - first).days))
    trading = {int(weekday) for weekday in hours.weekdays}
    return any(day.isoweekday() not in trading for day in held)


def _local(instant: int, tz: str) -> datetime:
    """`instant` as the wall clock of `tz` shows it."""
    utc = pl.Series([instant], dtype=pl.Int64).cast(pl.Datetime("ns", "UTC"))
    return utc.dt.convert_time_zone(tz).dt.replace_time_zone(None).item()
