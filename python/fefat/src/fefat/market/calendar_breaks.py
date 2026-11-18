"""Bars in a break that reach the next open (step 5.15, ADR-0022): a break that holds a bar
opening after the close and closing at the next session's open marks a stretch a platform
stamped early, since nothing prints in the minute before an open, where no offset of the whole
file explains it (`fefat.market.calendar_offset`). The calendar check reports such breaks
(`fefat.market.calendar_check`), and an import refuses a file that holds one, or, told to
(`BarsInBreaks.LEAVE_OUT`), leaves out the sessions beside them: the session before and the
session after each such break, and every session joined to one of those by a break that holds
a bar, repeating until none joins; and with them every other session whose last bar ends a bar
before its close, as a session a bar early does (D-104). No record of a session joined to such
a break by breaks that hold a bar is stored, nor of a session that ends so; a stretch that runs
on past a break without a bar, and ends no session so, keeps its far side (ADR-0022's limits).
Bars in other breaks stay (D-43).

    found = breaks_with_bars(dataset, bars.lazy(), sessions)
    kept = bars if found is None else without_the_sessions_left_out(bars, found)
"""

from collections.abc import Iterable
from datetime import date
from enum import StrEnum

import polars as pl
from pydantic import Field

from fefat.market.calendar import SessionTable, counted
from fefat.market.layout import Dataset
from fefat.market.schema import BarSchemaName, FrozenModel

_LISTED_AT_MOST = 10
"""How many trade dates a line names before it says how many more there are."""
REACHES_THE_NEXT_OPEN = (pl.col("ts_open") > pl.col("session_close")) & (
    pl.col("ts_close") == pl.col("next_open")
)
"""Whether a bar beside its session (`bars_with_their_sessions`) opens after the close and
closes at the next session's open: the edge of a stretch a platform stamped early, which the
calendar's offsets read too (`fefat.market.calendar_offset`)."""
ENDS_A_BAR_EARLY = pl.col("inside") & ~pl.col("last_bucket") & pl.col("bucket_before_the_last")
"""Whether a session of `session_edges` holds bars whose last ends a bar before the close: no
bar in its last bucket and one in the bucket before, as a session stamped a bar early, its
bars' opens read as their closes, ends."""


class BarsInBreaks(StrEnum):
    """What an import does with a file whose breaks hold a bar closing at the next open: refuse
    the file, or leave out those bars with the sessions beside them (ADR-0022)."""

    REFUSE = "refuse"
    LEAVE_OUT = "leave-out"

    @classmethod
    def _missing_(cls, value: object) -> "BarsInBreaks":
        options = ", ".join(each.value for each in cls)
        raise ValueError(
            f"Expected what an import does with bars in a break that reach the next open, one "
            f"of {options}, got {value!r}."
        )


class BreakWithBars(FrozenModel):
    """A break that holds a bar closing at the next session's open: the trade date of the
    session it follows, and how many bars it holds."""

    after: date
    bars: int = Field(ge=1)


class SessionLeftOut(FrozenModel):
    """A session the correction leaves out, by its trade date, and how many records the file
    holds of it, the bars in the break after it among them."""

    trade_date: date
    records: int = Field(ge=1)


class BreaksWithBars(FrozenModel):
    """A dataset's breaks that hold a bar closing at the next open, in order; the sessions
    beside them, in order, each with its records; and the other sessions whose last bar ends a
    bar before the close, as a session a bar early does, in order, which the correction leaves
    out with them (D-104)."""

    dataset: Dataset
    breaks: tuple[BreakWithBars, ...] = Field(min_length=1)
    sessions_beside: tuple[SessionLeftOut, ...] = Field(min_length=1)
    sessions_ending_a_bar_early: tuple[SessionLeftOut, ...] = ()

    def bars(self) -> int:
        """How many bars the breaks hold."""
        return sum(each.bars for each in self.breaks)

    def sessions_left_out(self) -> list[SessionLeftOut]:
        """The sessions the correction leaves out, those beside and those ending a bar early,
        in order."""
        left_out = [*self.sessions_beside, *self.sessions_ending_a_bar_early]
        return sorted(left_out, key=lambda each: each.trade_date)

    def records_left_out(self) -> int:
        """How many records the sessions left out hold, the bars in the breaks among them."""
        return sum(each.records for each in self.sessions_left_out())

    def trade_dates_beside(self) -> list[date]:
        """The trade dates of the sessions beside, in order."""
        return [each.trade_date for each in self.sessions_beside]

    def trade_dates_left_out(self) -> list[date]:
        """The trade dates of the sessions left out, in order."""
        return [each.trade_date for each in self.sessions_left_out()]

    def describe(self) -> str:
        """One line: the dataset, the breaks with their bars, and the sessions left out with
        their records, in counts and trade dates alone (D-21)."""
        heading = f"{self.dataset.relative_folder()} bars in a break"
        if len(self.breaks) == 1:
            (only,) = self.breaks
            found = (
                f"the break after the trade date {only.after} holds {counted(only.bars, 'bar')}, "
                "one closing at the next session's open"
            )
        else:
            dates = _listed(f"{each.after} ({each.bars:,})" for each in self.breaks)
            found = (
                f"{len(self.breaks)} breaks hold {counted(self.bars(), 'bar')}, each with one "
                f"closing at the next session's open, after the trade dates {dates}"
            )
        ending = len(self.sessions_ending_a_bar_early)
        others = (
            f" and {counted(ending, 'other session')} whose last bar ends a bar before the "
            "close, as a session a bar early does"
            if ending
            else ""
        )
        return (
            f"{heading}: {found}, as a stretch a platform stamped early holds; the sessions "
            f"beside{others}, {self.sessions_text()}"
        )

    def sessions_text(self) -> str:
        """The sessions left out, as their records and trade dates: `2,761 records of the trade
        dates 2026-03-06, 2026-03-09`, the bars in the breaks among them."""
        left_out = _listed(str(day) for day in self.trade_dates_left_out())
        return f"{counted(self.records_left_out(), 'record')} of the trade dates {left_out}"


def breaks_with_bars(
    dataset: Dataset, bars: pl.LazyFrame, sessions: SessionTable
) -> BreaksWithBars | None:
    """The breaks of `bars`, intraday bars of `dataset` dated by `trade_date`, that hold a bar
    opening after the close and closing at the next open, with the sessions beside them and
    those ending a bar early (module docstring); none where no break does."""
    bounded = bars_with_their_sessions(bars, sessions)
    if bounded is None:
        return None
    edges = session_edges(bounded, _bar_width(dataset))
    reaching = edges.filter("reaches_the_next_open")
    if reaching.is_empty():
        return None
    with_bars = set(edges.filter(pl.col("in_the_break") > 0).get_column("trade_date").to_list())
    beside = _sessions_beside(reaching.get_column("trade_date").to_list(), with_bars, sessions)
    is_beside = pl.col("trade_date").is_in(sorted(beside))
    return BreaksWithBars(
        dataset=dataset,
        breaks=tuple(
            BreakWithBars(after=day, bars=count)
            for day, count in reaching.select("trade_date", "in_the_break").rows()
        ),
        sessions_beside=_left_out(edges.filter(is_beside)),
        sessions_ending_a_bar_early=_left_out(edges.filter(~is_beside & ENDS_A_BAR_EARLY)),
    )


def without_the_sessions_left_out(records: pl.DataFrame, found: BreaksWithBars) -> pl.DataFrame:
    """`records`, dated by `trade_date`, without those of the sessions `found` leaves out, the
    bars in its breaks among them; nothing is moved or changed."""
    return records.filter(~pl.col("trade_date").is_in(found.trade_dates_left_out()))


def bars_with_their_sessions(bars: pl.LazyFrame, sessions: SessionTable) -> pl.LazyFrame | None:
    """The `trade_date`, `ts_open`, and `ts_close` of `bars`, each beside the `session_open` and
    `session_close` of its session and the `next_open` of the session after it, which
    `REACHES_THE_NEXT_OPEN` reads; none without bars."""
    first, last = (
        bars.select(first=pl.col("trade_date").min(), last=pl.col("trade_date").max())
        .collect(engine="streaming")
        .row(0)
    )
    if first is None:
        return None
    bounds = sessions.between_with_next_opens(first, last).select(
        "trade_date", "next_open", session_open="open", session_close="close"
    )
    return bars.select("trade_date", "ts_open", "ts_close").join(bounds.lazy(), on="trade_date")


def session_edges(bounded: pl.LazyFrame, width: int) -> pl.DataFrame:
    """A row per trade date of bars `width` long beside their sessions
    (`bars_with_their_sessions`), in order: its session's open and the next session's, its
    records, how many bars open in the break after it, at or after the close, whether a bar
    opens inside the session, whether one opens after the close and closes at the next open,
    whether a bar opens in the session's last bucket and in the bucket before it, and whether
    the session holds a bar opening at its close while its first bar opens a bar after its
    open."""
    opens, session_open, session_close = (
        pl.col(name) for name in ("ts_open", "session_open", "session_close")
    )
    last_bucket = session_open + (session_close - session_open - 1) // width * width
    return (
        bounded.group_by("trade_date")
        .agg(
            session_open.first(),
            pl.col("next_open").first(),
            records=pl.len(),
            in_the_break=(opens >= session_close).sum(),
            inside=(opens < session_close).any(),
            reaches_the_next_open=REACHES_THE_NEXT_OPEN.any(),
            last_bucket=(opens == last_bucket).any(),
            bucket_before_the_last=(opens == last_bucket - width).any(),
            late=(opens == session_close).any() & (opens.min() == session_open.first() + width),
        )
        .sort("trade_date")
        .collect(engine="streaming")
    )


def _bar_width(dataset: Dataset) -> int:
    schema_name = dataset.schema_name
    if not isinstance(schema_name, BarSchemaName):
        raise ValueError(
            f"Expected a dataset of bars, whose breaks can hold bars, got "
            f"{dataset.relative_folder()}."
        )
    return schema_name.timeframe.nominal_nanoseconds()


def _left_out(edges: pl.DataFrame) -> tuple[SessionLeftOut, ...]:
    return tuple(
        SessionLeftOut(trade_date=day, records=count)
        for day, count in edges.select("trade_date", "records").rows()
    )


def _sessions_beside(
    reaching: list[date], with_bars: set[date], sessions: SessionTable
) -> set[date]:
    """The sessions before and after each break of `reaching`, by the trade dates it follows,
    and every session joined to one of them by a break of `with_bars`, which hold a bar,
    repeating until none joins."""
    beside = {*reaching, *(sessions.following(day).trade_date for day in reaching)}
    while True:
        later = {sessions.following(day).trade_date for day in beside if day in with_bars}
        earlier = {sessions.preceding(day).trade_date for day in beside} & with_bars
        if later <= beside and earlier <= beside:
            return beside
        beside |= later | earlier


def _listed(texts: Iterable[str]) -> str:
    listed = list(texts)
    shown = ", ".join(listed[:_LISTED_AT_MOST])
    if len(listed) <= _LISTED_AT_MOST:
        return shown
    return f"{shown}, and {len(listed) - _LISTED_AT_MOST:,} more"
