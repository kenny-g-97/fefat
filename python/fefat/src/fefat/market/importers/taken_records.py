"""The records an import of a trader's file takes under its choice for bars in a break (step
5.15, ADR-0022): the records as read, or, told to leave them out, the records without the
sessions beside the breaks that hold a bar closing at the next open and without the sessions
whose last bar ends a bar before the close (`fefat.market.calendar_breaks`, D-104). The
correction applies only to a file of one contract, since the calendar checks a file's contracts
together and the records one leaves could hide another's offset, and only where the records it
leaves are some and, checked again with the sessions ending a bar early still among them, show
no offset and can still be timed by the calendar, since one bar before one open may be the only
sign of a thin file stamped a bar early, and leaving out such a sign would make the rest look
testable; otherwise the file is refused under either choice. Told to leave them out,
a file without such a break is refused, so that the raw manifest records the choice only where
sessions were left out.

    taken = taken_records(dataset, mapped, BarsInBreaks.LEAVE_OUT)
"""

from dataclasses import dataclass, replace

import polars as pl

from fefat.market.calendar import SessionTable
from fefat.market.calendar_breaks import BarsInBreaks, BreaksWithBars, without_the_sessions_left_out
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
    contracts = mapped.records.get_column("contract").n_unique()
    if contracts > 1:
        return replace(as_read, refusals=(_of_several_contracts(dataset, contracts),))
    (found,) = calendar.breaks_with_bars
    timed = mapped.records.filter(~pl.col("trade_date").is_in(found.trade_dates_beside()))
    kept = replace(mapped, records=without_the_sessions_left_out(mapped.records, found))
    refusal = _why_not_left_out(dataset, timed, kept.records, mapped.sessions)
    if refusal is not None:
        return replace(as_read, refusals=(refusal,))
    if not leaving_out:
        return as_read
    kept_calendar = check_records(dataset, kept.records.lazy(), kept.sessions)
    return TakenRecords(records=kept, calendar=kept_calendar, left_out=found, refusals=())


def _why_not_left_out(
    dataset: Dataset, timed: pl.DataFrame, kept: pl.DataFrame, sessions: SessionTable
) -> str | None:
    """Why the records the correction leaves, `kept`, cannot be taken: none left, or an offset
    or a timing the calendar cannot test in `timed`, the records without the sessions beside
    the breaks, those ending a bar early still among them; none where they can."""
    if kept.is_empty():
        return _not_left_out(dataset, "the sessions it leaves out hold every record of the file")
    calendar = check_records(dataset, timed.lazy(), sessions)
    if calendar.offsets:
        (offset,) = calendar.offsets
        return _not_left_out(dataset, f"without the sessions beside them, {offset.describe()}")
    if not timing_checked(dataset, timed, sessions):
        return _not_left_out(
            dataset,
            "without the sessions beside them, the calendar could not check the time zone and "
            "bar stamping of the records left, which the sessions left out may alone have shown, "
            "so compare the file's bars with the platform's chart",
        )
    return None


def _of_several_contracts(dataset: Dataset, contracts: int) -> str:
    return _not_left_out(
        dataset,
        f"the file holds {contracts} contracts, which the calendar checks together, so the "
        "records one leaves could hide another's offset; leaving them out applies to a file of "
        "one contract",
    )


def _not_left_out(dataset: Dataset, why: str) -> str:
    return f"{dataset.relative_folder()} bars in a break, not to be left out: {why}"


def _nothing_to_leave_out(dataset: Dataset) -> str:
    return (
        f"{dataset.relative_folder()} no bars in a break: the file holds no break with a bar "
        "closing at the next open, whose sessions --bars-in-breaks leave-out would leave out, so "
        "import it without the option"
    )
