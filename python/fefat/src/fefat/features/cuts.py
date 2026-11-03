"""The leak detector's cuts (step 3.4, `02-engine-and-data.md` §6, D-71): the instants at which
`fefat.features.validation` cuts every input a feature reads at its own availability, a bar at its
`ts_close`, to compare the values before each cut with those the whole range gives. A cut is an
instant, never a trade date.

The adversarial cuts come from the session table and the roll calendar: at each stop of trading
(`fefat.market.trading_stops`), a session's close or a holiday's halt, then a nanosecond after it,
inside its break, or over the weekend when the break holds one, a nanosecond before the next open,
and at it; at each roll's open and at the close of the new front's first bar; and on each higher
timeframe a feature reads, one signal bar before a bar of it closes, while it is in progress, and
at its close. Random cuts fall at the closes of signal bars, and the stops kept where a window
holds more than asked for are drawn, from one seed, so that a validation repeats (D-11). Every
cut lies at or after the close of the window's first session, so that each compares a session of
values at least: a feature whose warm-up reaches past the data then compares nothing at its first
cuts, and fails."""

import random
from collections.abc import Iterator, Sequence
from datetime import date
from enum import StrEnum

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.schema import FrozenModel
from fefat.market.trading_stops import TradingStop, trading_stops

HIGHER_TIMEFRAME_BARS = 4
"""The bars of each higher timeframe a validation cuts inside and at the close of."""


class CutKind(StrEnum):
    """Why a cut falls where it does (module docstring)."""

    SESSION_CLOSE = "session_close"
    HOLIDAY_HALT = "holiday_halt"
    AFTER_STOP = "after_stop"
    IN_BREAK = "in_break"
    WEEKEND = "weekend"
    BEFORE_OPEN = "before_open"
    AT_OPEN = "at_open"
    ROLL_OPEN = "roll_open"
    ROLL_FIRST_BAR = "roll_first_bar"
    HIGHER_TIMEFRAME_LAST_BAR = "higher_timeframe_last_bar"
    HIGHER_TIMEFRAME_CLOSE = "higher_timeframe_close"
    RANDOM = "random"


class Cut(FrozenModel):
    """An instant, in nanoseconds since the Unix epoch, UTC, at which every input is cut, and
    why, by each kind that falls there."""

    instant: int
    kinds: tuple[CutKind, ...]


def cuts_of(
    window: pl.DataFrame,
    sessions: SessionTable,
    roll_days: Sequence[date],
    higher: Sequence[pl.DataFrame],
    chooser: random.Random,
    stops: int,
    random_cuts: int,
) -> tuple[Cut, ...]:
    """The cuts of a window, the signal bars' `trade_date` and `ts_close` from its first trade
    date to its last, in order: the stops of trading, at most `stops` of them but never fewer
    than the first and the last, a weekend, and a holiday halt where the window holds them, the
    others drawn by `chooser`; the
    rolls of `roll_days`; `HIGHER_TIMEFRAME_BARS` bars of each frame of `higher`, the
    `trade_date` and `ts_close` of a higher timeframe's bars in the window, after its first
    session; and `random_cuts` closes of the window's signal bars after its first session."""
    days = window.get_column("trade_date").unique().sort().to_list()
    floor = sessions.session(days[0]).close
    later = window.filter(pl.col("trade_date") > days[0])
    found: dict[int, list[CutKind]] = {}
    instants = [
        *_at_stops(_kept_stops(sessions, days, floor, chooser, stops), sessions),
        *_at_rolls(window, sessions, [day for day in roll_days if day in days]),
        *(each for frame in higher for each in _at_higher_bars(frame, later, chooser)),
        *((close, CutKind.RANDOM) for close in _drawn(later, chooser, random_cuts)),
    ]
    for instant, kind in instants:
        if instant >= floor:
            found.setdefault(instant, []).append(kind)
    order = list(CutKind)
    return tuple(
        Cut(instant=instant, kinds=tuple(sorted(set(kinds), key=order.index)))
        for instant, kinds in sorted(found.items())
    )


def _kept_stops(
    sessions: SessionTable, days: Sequence[date], floor: int, chooser: random.Random, stops: int
) -> list[tuple[date, TradingStop]]:
    """The stops of trading of `days` from `floor` on, at most `stops` of them but never fewer
    than the first and the last, the first weekend, and the first holiday halt, the others drawn
    by `chooser`."""
    every = [
        (day, stop) for day in days for stop in trading_stops(sessions, day) if stop.start >= floor
    ]
    if len(every) <= stops:
        return every
    halts = [each for each in every if each[1].start != sessions.session(each[0]).close]
    weekends = [each for each in every if each[1].weekend]
    kept = list(dict.fromkeys([every[0], every[-1], *weekends[:1], *halts[:1]]))
    others = [each for each in every if each not in kept]
    kept += chooser.sample(others, max(0, stops - len(kept)))
    return sorted(kept, key=lambda each: each[1].start)


def _at_stops(
    kept: Sequence[tuple[date, TradingStop]], sessions: SessionTable
) -> Iterator[tuple[int, CutKind]]:
    for day, stop in kept:
        closes = stop.start == sessions.session(day).close
        yield stop.start, CutKind.SESSION_CLOSE if closes else CutKind.HOLIDAY_HALT
        yield stop.start + 1, CutKind.AFTER_STOP
        yield (
            (stop.start + stop.resumes) // 2,
            CutKind.WEEKEND if stop.weekend else CutKind.IN_BREAK,
        )
        yield stop.resumes - 1, CutKind.BEFORE_OPEN
        yield stop.resumes, CutKind.AT_OPEN


def _at_rolls(
    window: pl.DataFrame, sessions: SessionTable, roll_days: Sequence[date]
) -> Iterator[tuple[int, CutKind]]:
    for day in roll_days:
        yield sessions.session(day).open, CutKind.ROLL_OPEN
        first = window.filter(pl.col("trade_date") == day).get_column("ts_close").min()
        if isinstance(first, int):
            yield first, CutKind.ROLL_FIRST_BAR


def _at_higher_bars(
    frame: pl.DataFrame, later: pl.DataFrame, chooser: random.Random
) -> Iterator[tuple[int, CutKind]]:
    """For bars of a higher timeframe drawn by `chooser` among those after the window's first
    session, the close of the signal bar before each bar's close, while it is in progress, and
    its close."""
    days = later.get_column("trade_date")
    within = pl.col("trade_date").is_between(days.min(), days.max())
    closes = frame.filter(within).get_column("ts_close").to_list()
    signal = later.get_column("ts_close").to_list()
    for close in sorted(chooser.sample(closes, min(HIGHER_TIMEFRAME_BARS, len(closes)))):
        inside = [each for each in signal if each < close]
        if inside:
            yield inside[-1], CutKind.HIGHER_TIMEFRAME_LAST_BAR
        yield close, CutKind.HIGHER_TIMEFRAME_CLOSE


def _drawn(later: pl.DataFrame, chooser: random.Random, count: int) -> list[int]:
    closes = later.get_column("ts_close").to_list()
    return sorted(chooser.sample(closes, min(count, len(closes))))
