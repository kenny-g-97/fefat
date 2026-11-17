"""The records an import of a trader's file takes under its choice for bars in a break (step
5.15, ADR-0022): the records as read, or, told to leave them out, the records without the
sessions beside the breaks that hold a bar closing at the next open
(`fefat.market.calendar_breaks`). The correction applies only where the records it leaves,
checked again, show no offset and the calendar can still test their timing, since one bar before
one open may be the only sign of a thin file stamped a bar early; otherwise the file is refused
under either choice. Told to leave them out, a file without such a break is refused, so that the
raw manifest records the choice only where sessions were left out.

    taken = taken_records(dataset, mapped, BarsInBreaks.LEAVE_OUT)
"""

from dataclasses import dataclass, replace

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.calendar_breaks import BarsInBreaks, BreaksWithBars, without_the_sessions_beside
from fefat.market.calendar_check import CalendarReport, check_records
from fefat.market.calendar_offset import timing_checked
from fefat.market.importers.profile_records import MappedRecords
from fefat.market.layout import Dataset


@dataclass(frozen=True)
class TakenRecords:
    """The records an import takes, their calendar check, the breaks it leaves out with the
    sessions beside them, if any, and what the choice refuses, if anything."""

    records: MappedRecords
    calendar: CalendarReport
    left_out: BreaksWithBars | None
    refusals: tuple[str, ...]


def taken_records(
    dataset: Dataset, mapped: MappedRecords, bars_in_breaks: BarsInBreaks
) -> TakenRecords:
    """The records of `mapped`, of `dataset`, an import takes under `bars_in_breaks` (module
    docstring)."""
    calendar = check_records(dataset, mapped.records.lazy(), mapped.sessions)
    as_read = TakenRecords(records=mapped, calendar=calendar, left_out=None, refusals=())
    leaving_out = bars_in_breaks is BarsInBreaks.LEAVE_OUT
    if not calendar.breaks_with_bars:
        if leaving_out and not calendar.offsets:
            return replace(as_read, refusals=(_nothing_to_leave_out(dataset),))
        return as_read
    (found,) = calendar.breaks_with_bars
    kept = replace(mapped, records=without_the_sessions_beside(mapped.records, found))
    kept_calendar = check_records(dataset, kept.records.lazy(), kept.sessions)
    refusal = _why_not_left_out(dataset, kept.records, kept_calendar, kept.sessions)
    if refusal is not None:
        return replace(as_read, refusals=(refusal,))
    if leaving_out:
        return TakenRecords(records=kept, calendar=kept_calendar, left_out=found, refusals=())
    return as_read


def _why_not_left_out(
    dataset: Dataset, records: pl.DataFrame, calendar: CalendarReport, sessions: SessionTable
) -> str | None:
    """Why the records left without the sessions beside the breaks cannot be taken: none left,
    an offset, or a timing the calendar cannot test; none where they can."""
    heading = f"{dataset.relative_folder()} bars in a break, not to be left out"
    if records.is_empty():
        return f"{heading}: the sessions beside them hold every record of the file"
    if calendar.offsets:
        (offset,) = calendar.offsets
        return f"{heading}: without the sessions beside them, {offset.describe()}"
    if not timing_checked(dataset, records, sessions):
        return (
            f"{heading}: without the sessions beside them, the calendar could not check the "
            "time zone and bar stamping of the records left, which the sessions left out may "
            "alone have shown, so compare the file's bars with the platform's chart"
        )
    return None


def _nothing_to_leave_out(dataset: Dataset) -> str:
    return (
        f"{dataset.relative_folder()} no bars in a break: the file holds no break with a bar "
        "closing at the next open, whose sessions --bars-in-breaks leave-out would leave out, so "
        "import it without the option"
    )
