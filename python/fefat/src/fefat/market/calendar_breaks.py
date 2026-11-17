"""Bars in a break that reach the next open (step 5.15, ADR-0022): a break that holds a bar
opening after the close and closing at the next session's open marks a stretch a platform
stamped early, since nothing prints in the minute before an open, where no offset of the whole
file explains it (`fefat.market.calendar_offset`). The calendar check reports such breaks
(`fefat.market.calendar_check`), and an import refuses a file that holds one, or, told to
(`BarsInBreaks.LEAVE_OUT`), leaves out the sessions beside them: the session before and the
session after each such break, and every session joined to one of those by a break that holds
a bar, repeating until none joins, so that no record of a stretch that touches such a break is
stored. Bars in other breaks stay (D-43).

    found = breaks_with_bars(dataset, bars.lazy(), sessions)
    kept = bars if found is None else without_the_sessions_beside(bars, found)
"""

from collections.abc import Iterable
from datetime import date
from enum import StrEnum

import polars as pl
from pydantic import Field

from fefat.market.calendar import SessionTable, counted
from fefat.market.layout import Dataset
from fefat.market.schema import FrozenModel

_LISTED_AT_MOST = 10
"""How many trade dates a line names before it says how many more there are."""


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


class SessionBeside(FrozenModel):
    """A session beside such a break, by its trade date, and how many records the file holds
    of it, the bars in the break after it among them."""

    trade_date: date
    records: int = Field(ge=1)


class BreaksWithBars(FrozenModel):
    """A dataset's breaks that hold a bar closing at the next open, in order, and the sessions
    beside them that the correction leaves out, in order, each with its records."""

    dataset: Dataset
    breaks: tuple[BreakWithBars, ...] = Field(min_length=1)
    sessions_beside: tuple[SessionBeside, ...] = Field(min_length=1)

    def bars(self) -> int:
        """How many bars the breaks hold."""
        return sum(each.bars for each in self.breaks)

    def records_beside(self) -> int:
        """How many records the sessions beside hold, the bars in the breaks among them."""
        return sum(each.records for each in self.sessions_beside)

    def trade_dates_beside(self) -> list[date]:
        """The trade dates of the sessions beside, in order."""
        return [each.trade_date for each in self.sessions_beside]

    def describe(self) -> str:
        """One line: the dataset, the breaks with their bars, and the sessions beside them with
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
        return (
            f"{heading}: {found}, as a stretch a platform stamped early holds; the sessions "
            f"beside, {self.sessions_text()}"
        )

    def sessions_text(self) -> str:
        """The sessions beside, as their records and trade dates: `2,761 records of the trade
        dates 2026-03-06, 2026-03-09`, the bars in the breaks among them."""
        beside = _listed(str(day) for day in self.trade_dates_beside())
        return f"{counted(self.records_beside(), 'record')} of the trade dates {beside}"


def breaks_with_bars(
    dataset: Dataset, bars: pl.LazyFrame, sessions: SessionTable
) -> BreaksWithBars | None:
    """The breaks of `bars`, dated by `trade_date`, that hold a bar opening after the close and
    closing at the next open, with the sessions beside them (module docstring); none where no
    break does."""
    dated = _dated_breaks(bars, sessions)
    reaching = dated.filter("reaches_the_next_open")
    if reaching.is_empty():
        return None
    with_bars = set(dated.filter(pl.col("in_the_break") > 0).get_column("trade_date").to_list())
    beside = _sessions_beside(reaching.get_column("trade_date").to_list(), with_bars, sessions)
    held = dated.filter(pl.col("trade_date").is_in(sorted(beside)) & (pl.col("records") > 0))
    return BreaksWithBars(
        dataset=dataset,
        breaks=tuple(
            BreakWithBars(after=day, bars=count)
            for day, count in reaching.select("trade_date", "in_the_break").rows()
        ),
        sessions_beside=tuple(
            SessionBeside(trade_date=day, records=count)
            for day, count in held.select("trade_date", "records").rows()
        ),
    )


def without_the_sessions_beside(records: pl.DataFrame, found: BreaksWithBars) -> pl.DataFrame:
    """`records`, dated by `trade_date`, without those of the sessions beside the breaks `found`
    holds, the bars in those breaks among them; nothing is moved or changed."""
    return records.filter(~pl.col("trade_date").is_in(found.trade_dates_beside()))


def _dated_breaks(bars: pl.LazyFrame, sessions: SessionTable) -> pl.DataFrame:
    """Per trade date of `bars`, in order: its records, how many bars open in the break after
    its session, at or after the close, and whether one opens after the close and closes at the
    next open."""
    first, last = (
        bars.select(first=pl.col("trade_date").min(), last=pl.col("trade_date").max())
        .collect(engine="streaming")
        .row(0)
    )
    if first is None:
        return pl.DataFrame(
            schema={
                "trade_date": pl.Date,
                "records": pl.UInt32,
                "in_the_break": pl.UInt32,
                "reaches_the_next_open": pl.Boolean,
            }
        )
    bounds = sessions.between_with_next_opens(first, last).select(
        "trade_date", "next_open", session_close="close"
    )
    opens, session_close = pl.col("ts_open"), pl.col("session_close")
    return (
        bars.select("trade_date", "ts_open", "ts_close")
        .join(bounds.lazy(), on="trade_date")
        .group_by("trade_date")
        .agg(
            records=pl.len(),
            in_the_break=(opens >= session_close).sum(),
            reaches_the_next_open=(
                (opens > session_close) & (pl.col("ts_close") == pl.col("next_open"))
            ).any(),
        )
        .sort("trade_date")
        .collect(engine="streaming")
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
