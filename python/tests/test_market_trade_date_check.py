"""A change of the session calendar between two imports (step 5.16, ADR-0024, Done means 3): the
store keeps the trade dates its records were imported with, so after a halt is added on a day the
rules missed, the check lists the stored records the calendar dates otherwise now, and the same
records imported again, which the calendar now dates on the next trade date, are refused, for
bars kept by month across a month's end and for prints kept by trade date. The records are ES
June 2026's from the tests' generator, a walk of up to four ticks a minute, and prints made up
from their seconds and places."""

import os
from datetime import date, time
from pathlib import Path

import polars as pl
import pytest

from export_samples import IMPORTED_ON, PRESETS, written_export
from fefat.config import resolve_paths
from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.calendar_definition import CalendarId, Halt
from fefat.market.importers.file_import import FileImportRequest, import_file
from fefat.market.importers.file_report import AlreadyImported, FileImportReport
from fefat.market.instruments import STATIC_TABLE, InstrumentTable
from fefat.market.store import Store
from fefat.market.trade_date_check import verify_trade_dates
from generated_minutes import listing, minutes_of, ninjatrader_lines
from test_market_importers_merge_properties import SECOND_STAMPED_PRINTS, tree
from test_market_importers_stored_offset import prints_export, prints_of

MINUTE = 60_000_000_000
MONDAY, TUESDAY = date(2026, 3, 30), date(2026, 3, 31)
WEDNESDAY, THURSDAY = date(2026, 4, 1), date(2026, 4, 2)
ESM2026 = listing("ESM2026", 1003, ("2026-03-30", "2026-04-02"), ("2026-03-30", "2026-04-02"))
HALTED = Halt(day=TUESDAY, closes_at=time(12), source="https://www.cmegroup.com/trading-hours.html")
"""A halt at noon on Tuesday 2026-03-31, as a correction of a holiday the rules missed gives:
its trading belongs to Wednesday's trade date, whose session opens on Monday evening."""


def halted_on_tuesday() -> InstrumentTable:
    """The instrument table with ES's calendar holding `HALTED`."""
    calendar = BUILT_IN[CalendarId.CME_EQUITY_INDEX]
    halted = calendar.model_copy(update={"holidays": (*calendar.holidays, HALTED)})
    return InstrumentTable(
        versions=tuple(
            version.model_copy(update={"calendar": halted}) if version.root == "ES" else version
            for version in STATIC_TABLE.versions
        )
    )


@pytest.fixture
def sessions() -> SessionTable:
    return sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], resolve_paths(os.environ).cache_dir)


def the_store() -> Store:
    return Store(resolve_paths(os.environ).data_dir)


def imported(
    request: FileImportRequest, instruments: InstrumentTable
) -> FileImportReport | AlreadyImported:
    return import_file(
        request,
        the_store(),
        resolve_paths(os.environ).cache_dir,
        imported_on=IMPORTED_ON,
        instruments=instruments,
    )


def minutes_export(folder: Path, bars: pl.DataFrame) -> FileImportRequest:
    """`bars` as NinjaTrader exports ESM2026, in `folder`."""
    path = written_export(folder, "ES 06-26.Last.txt", ninjatrader_lines(bars))
    return FileImportRequest(path=path, profile=PRESETS["ninjatrader"])


def test_bars_imported_again_under_a_changed_calendar_are_refused_across_a_months_end(
    tmp_path: Path, sessions: SessionTable
) -> None:
    # Done means 3: with the halt, the same bars of Tuesday's session fall in April's month,
    # beside March's, which holds them under 2026-03-31, and a merge would store them twice.
    bars = minutes_of(ESM2026, sessions.between(MONDAY, THURSDAY))
    imported(minutes_export(tmp_path / "first", bars), STATIC_TABLE)
    before = tree(the_store().folder)
    refusal = (
        "after those the store holds of ESM2026 under 2026-03, which end at "
        "2026-03-31T20:59:00Z, got records from 2026-03-30T22:00:00Z"
    )

    with pytest.raises(ValueError, match=refusal):
        imported(minutes_export(tmp_path / "again", bars.head(-1)), halted_on_tuesday())

    assert tree(the_store().folder) == before


def test_prints_imported_again_under_a_changed_calendar_are_refused_beside_their_trade_date(
    tmp_path: Path, sessions: SessionTable
) -> None:
    # Tuesday's prints, dated on Wednesday under the halt, fall in Wednesday's partition beside
    # Tuesday's, which holds them.
    prints = [
        record
        for day in (MONDAY, TUESDAY, WEDNESDAY)
        for record in prints_of(sessions.session(day).open + 10 * MINUTE, 20)
    ]
    first = prints_export(tmp_path / "first", prints, contract="ESM2026")
    imported(FileImportRequest(path=first, profile=SECOND_STAMPED_PRINTS), STATIC_TABLE)
    before = tree(the_store().folder)
    again = prints_export(tmp_path / "again", prints[:-1], contract="ESM2026")

    with pytest.raises(ValueError, match="after those the store holds of ESM2026 under 2026-03-31"):
        imported(FileImportRequest(path=again, profile=SECOND_STAMPED_PRINTS), halted_on_tuesday())

    assert tree(the_store().folder) == before


def test_the_check_lists_the_stored_bars_a_changed_calendar_dates_otherwise(
    tmp_path: Path, sessions: SessionTable
) -> None:
    # Done means 3: the bars of Tuesday's session stored under 2026-03-31, which the halt dates
    # on 2026-04-01; none before the change.
    bars = minutes_of(ESM2026, sessions.between(MONDAY, THURSDAY))
    imported(minutes_export(tmp_path / "first", bars), STATIC_TABLE)
    cache = resolve_paths(os.environ).cache_dir

    before = verify_trade_dates(the_store(), cache, STATIC_TABLE, "ES")
    after = verify_trade_dates(the_store(), cache, halted_on_tuesday(), "ES")

    assert before.dated_otherwise == ()
    assert before.summary() == (
        f"Records checked: {bars.height:,} of 1 dataset. Dated otherwise than the calendar dates "
        "them now: none."
    )
    (found,) = after.dated_otherwise
    assert found.records == bars.filter(pl.col("trade_date") == TUESDAY).height
    assert found.describe() == (
        "ninjatrader/ohlcv-1m/root=ES ESM2026 2026-03-31: 1,380 records from "
        "2026-03-30T22:00:00Z to 2026-03-31T20:59:00Z, which the calendar dates 2026-04-01 now"
    )
    assert after.summary().splitlines()[-1] == (
        "To date them again, delete the stored data, on the instrument's page in the app or "
        "with fefat data delete ninjatrader ES, and import its files again."
    )


def test_the_check_lists_the_stored_prints_a_changed_calendar_dates_otherwise(
    tmp_path: Path, sessions: SessionTable
) -> None:
    opens = {day: sessions.session(day).open + 10 * MINUTE for day in (MONDAY, TUESDAY)}
    tuesday = prints_of(opens[TUESDAY], 20)
    prints = [*prints_of(opens[MONDAY], 20), *tuesday]
    path = prints_export(tmp_path / "first", prints, contract="ESM2026")
    imported(FileImportRequest(path=path, profile=SECOND_STAMPED_PRINTS), STATIC_TABLE)

    report = verify_trade_dates(
        the_store(), resolve_paths(os.environ).cache_dir, halted_on_tuesday()
    )

    (found,) = report.dated_otherwise
    assert (found.stored_trade_date, found.trade_date_now) == (TUESDAY, WEDNESDAY)
    assert (found.records, report.records_checked) == (len(tuesday), len(prints))


def test_the_check_of_a_product_the_store_holds_none_of_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected trades or bars of ES in the store, got none"):
        verify_trade_dates(the_store(), resolve_paths(os.environ).cache_dir, STATIC_TABLE, "ES")
