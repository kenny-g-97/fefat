"""A file refused for its bars in a break, and imported without them and the sessions beside
them once the trader approves (step 5.15, ADR-0022): Done means 1, 6, and 7 through the file
importer. The files are NinjaTrader exports of ESH2026's 1-minute bars of ten whole sessions,
2026-02-02 to 02-13, from the tests' generator, which writes no bar in a break unless a test adds
one; the store is the test's data folder, which the leak detector reads."""

import os
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import polars as pl
import pytest

import fefat as ff
from export_samples import IMPORTED_ON, PRESETS, written_export
from fefat.config import resolve_paths
from fefat.features.examples import rsi
from fefat.market import instruments
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.calendar_breaks import BarsInBreaks
from fefat.market.importers.file_import import FileImportRequest, import_file, preview_file
from fefat.market.importers.file_report import AlreadyImported, FileImportReport, FilePreview
from fefat.market.raw_manifest import checked_raw_path
from fefat.market.saved_instruments import instrument_table
from fefat.market.store import Store
from generated_minutes import listing, minutes_of, ninjatrader_lines
from test_market_importers_previews import priced

MINUTE = 60_000_000_000
FIRST, LAST = date(2026, 2, 2), date(2026, 2, 13)
ESH2026 = listing("ESH2026", 1001, ("2026-02-02", "2026-02-13"), ("2026-02-02", "2026-02-13"))
ESM2026 = listing("ESM2026", 1003, ("2026-02-02", "2026-02-13"), ("2026-02-02", "2026-02-13"))
TUESDAY, WEDNESDAY, THURSDAY = date(2026, 2, 3), date(2026, 2, 4), date(2026, 2, 5)
LEAVE_OUT = BarsInBreaks.LEAVE_OUT
COMPARED = ("ts_open", "ts_close", "open", "high", "low", "close", "volume")
"""The columns a NinjaTrader export carries, which the store's bars keep as the file has them."""
REFUSED_TO_FIX = "It would be refused: fix the profile, or the file, and preview it again."


@pytest.fixture
def sessions() -> SessionTable:
    calendar = instruments.get("ES").session_calendar()
    return sessions_of(calendar, resolve_paths(os.environ).cache_dir)


@pytest.fixture
def bars(sessions: SessionTable) -> pl.DataFrame:
    """ESH2026's bars of the ten sessions, a bar in every minute."""
    return minutes_of(ESH2026, sessions.between(FIRST, LAST))


def with_the_break_after(bars: pl.DataFrame, day: date, sessions: SessionTable) -> pl.DataFrame:
    """`bars` and a bar in every minute of the break after `day`'s session, priced as its last
    bar, the last closing at the next session's open."""
    last = bars.filter(pl.col("trade_date") == day).tail(1)
    opens = range(sessions.session(day).close, sessions.following(day).open, MINUTE)
    added = [
        last.with_columns(ts_open=pl.lit(opened), ts_close=pl.lit(opened + MINUTE))
        for opened in opens
    ]
    return pl.concat([bars, *added]).sort("ts_open")


def moved(bars: pl.DataFrame, nanoseconds: int, since: date = FIRST) -> pl.DataFrame:
    """`bars`, those of the trade dates from `since` on moved by `nanoseconds`."""
    shift = pl.when(pl.col("trade_date") >= since).then(nanoseconds).otherwise(0)
    return bars.with_columns(pl.col("ts_open") + shift, pl.col("ts_close") + shift)


def exported(folder: Path, bars: pl.DataFrame) -> Path:
    """`bars` written as NinjaTrader exports ESH2026, in `folder`."""
    return written_export(folder, "ES 03-26.Last.txt", ninjatrader_lines(bars))


def databento_lines(*contracts: tuple[str, pl.DataFrame]) -> list[str]:
    """The bars of each contract, under its Databento symbol, as a Databento CSV of 1-minute
    bars writes them, the `databento-csv` preset's layout: each stamped at its open, in
    nanoseconds, and its prices in units of 1e-9."""
    columns = ("ts_open", "rtype", "publisher_id", "instrument_id", "open", "high", "low")
    columns += ("close", "volume", "symbol")
    rows = pl.concat(
        bars.with_columns(rtype=pl.lit(33), publisher_id=pl.lit(1), symbol=pl.lit(symbol)).select(
            columns
        )
        for symbol, bars in contracts
    ).sort("ts_open", "symbol")
    line = pl.concat_str([pl.col(name).cast(pl.String) for name in columns], separator=",")
    header = "ts_event,rtype,publisher_id,instrument_id,open,high,low,close,volume,symbol"
    return [header, *rows.select(line).to_series().to_list()]


def request_of(
    path: Path, choice: BarsInBreaks = BarsInBreaks.REFUSE, **changes: str
) -> FileImportRequest:
    return FileImportRequest(
        path=path, profile=PRESETS["ninjatrader"], bars_in_breaks=choice, **changes
    )


def the_store() -> Store:
    return Store(resolve_paths(os.environ).data_dir)


def previewed(request: FileImportRequest) -> FilePreview:
    store = the_store()
    cache = resolve_paths(os.environ).cache_dir
    return preview_file(request, store, instrument_table(store.folder), cache)


def imported(request: FileImportRequest) -> FileImportReport | AlreadyImported:
    store = the_store()
    return import_file(
        request,
        store,
        resolve_paths(os.environ).cache_dir,
        imported_on=IMPORTED_ON,
        instruments=instrument_table(store.folder),
    )


def stored_bars() -> pl.DataFrame:
    store = the_store()
    return pl.concat(
        store.scan_partition(file.partition).collect() for file in store.list_partitions()
    )


def beside(*days: date) -> pl.Expr:
    return pl.col("trade_date").is_in(list(days))


def test_a_file_with_bars_through_a_break_is_refused_for_them_with_their_trade_dates(
    tmp_path: Path, bars: pl.DataFrame, sessions: SessionTable
) -> None:
    # Done means 1 through the importer: a bar in every minute of the break after Wednesday,
    # read today as a file stamped a bar early. The preview names the break, its bars, and the
    # sessions beside it, with what to do; the import is refused, and nothing is written.
    path = exported(tmp_path, with_the_break_after(bars, WEDNESDAY, sessions))

    preview = previewed(request_of(path))
    (found,) = preview.reading.calendar.breaks_with_bars

    assert [(each.after, each.bars) for each in found.breaks] == [(WEDNESDAY, 60)]
    assert found.trade_dates_beside() == [WEDNESDAY, THURSDAY]
    assert preview.reading.calendar.offsets == ()
    assert preview.refusals() == [found.describe()]
    assert preview.summary().splitlines()[-1] == (
        "It would be refused for its bars in a break: compare the sessions beside them with the "
        "platform's chart, and where the platform stamped that stretch early, import the file "
        "with --bars-in-breaks leave-out, which leaves them out."
    )
    with pytest.raises(
        ValueError, match="the break after the trade date 2026-02-04 holds 60 bars"
    ) as refused:
        imported(request_of(path))
    assert "import the file with --bars-in-breaks leave-out" in str(refused.value)
    assert not the_store().folder.exists()


def test_told_to_leave_them_out_an_import_takes_the_file_without_the_sessions_beside(
    tmp_path: Path, bars: pl.DataFrame, sessions: SessionTable
) -> None:
    # Done means 6: the preview and the report count the records left out with their trade
    # dates; the store holds every other bar of the file and none of the sessions beside the
    # break; and the raw manifest records the choice among the import's arguments.
    path = exported(tmp_path, with_the_break_after(bars, WEDNESDAY, sessions))
    request = request_of(path, LEAVE_OUT)
    kept = bars.filter(~beside(WEDNESDAY, THURSDAY))
    left_out = bars.height + 60 - kept.height

    preview = previewed(request)
    report = imported(request)

    assert isinstance(report, FileImportReport)
    for reading in (preview.reading, report.reading):
        assert reading.refusals() == []
        assert reading.left_out is not None
        assert reading.left_out.records_beside() == left_out
        assert reading.records == kept.height
    assert preview.summary().splitlines()[-1] == "It would import as it is."
    assert (
        f"  Left out: {left_out:,} records of the trade dates 2026-02-04, 2026-02-05, beside 1 "
        "break with a bar closing at the next open"
    ) in report.summary().splitlines()
    assert stored_bars().select(COMPARED).equals(kept.select(COMPARED))
    recorded = the_store().raw.manifest().file_at(checked_raw_path(report.raw_path))
    assert recorded is not None
    assert recorded.vendor_version == (
        "import profile ninjatrader, bars in a break left out with the sessions beside them"
    )


def test_a_file_imported_under_one_choice_is_refused_under_the_other(
    tmp_path: Path, bars: pl.DataFrame, sessions: SessionTable
) -> None:
    # Done means 6, D-50: a file is imported once, as its first import read it, both ways.
    breaks = exported(tmp_path / "breaks", with_the_break_after(bars, WEDNESDAY, sessions))
    clean = exported(tmp_path / "clean", bars)
    once = "a file is imported once, as its first import read it"

    imported(request_of(breaks, LEAVE_OUT))
    imported(request_of(clean))

    for refused in (request_of(breaks), request_of(clean, LEAVE_OUT)):
        with pytest.raises(ValueError, match=once):
            previewed(refused)
        with pytest.raises(ValueError, match=once):
            imported(refused)
    assert isinstance(imported(request_of(breaks, LEAVE_OUT)), AlreadyImported)


def test_a_later_file_that_holds_the_sessions_left_out_adds_them(
    tmp_path: Path, bars: pl.DataFrame, sessions: SessionTable
) -> None:
    # The sessions left out are a gap a clean export fills: the merge adds them as new sessions
    # and holds the rest already (ADR-0021, ADR-0022).
    imported(
        request_of(
            exported(tmp_path / "breaks", with_the_break_after(bars, WEDNESDAY, sessions)),
            LEAVE_OUT,
        )
    )

    report = imported(request_of(exported(tmp_path / "clean", bars)))

    assert isinstance(report, FileImportReport)
    assert [day.trade_date for day in report.merge.new_sessions] == [WEDNESDAY, THURSDAY]
    assert report.merge.records_held == bars.filter(~beside(WEDNESDAY, THURSDAY)).height
    assert stored_bars().select(COMPARED).equals(bars.select(COMPARED))


def test_the_leak_detector_passes_on_a_store_the_correction_wrote(
    tmp_path: Path, bars: pl.DataFrame, sessions: SessionTable
) -> None:
    # Done means 6: the window holds the two sessions left out, 02-09 and 02-10, a gap in the
    # series, and starts three sessions after the data, so that every cut has values to compare.
    monday = date(2026, 2, 9)
    imported(
        request_of(exported(tmp_path, with_the_break_after(bars, monday, sessions)), LEAVE_OUT)
    )
    assert date(2026, 2, 10) not in stored_bars().get_column("trade_date").to_list()

    report = ff.features.validate(rsi(n=14), "ES", "5m", "2026-02-05", "2026-02-12", seed=3)

    assert report.passed, report.summary()
    assert min(count for cut in report.cuts for count in cut.compared.values()) > 0


@pytest.mark.parametrize("case", ["a bar early", "a bar early from 02-09", "hours off"])
def test_a_file_with_an_offset_is_refused_under_the_choice_and_offered_no_correction(
    tmp_path: Path, bars: pl.DataFrame, case: str
) -> None:
    # Done means 7: a file stamped a bar early, one whose sessions from 02-09 on are, as two
    # exports joined can be, and one read hours off, its UTC times named Chicago's, are each
    # refused for their offset under the choice, and nothing offers to leave anything out.
    files = {
        "a bar early": (moved(bars, -MINUTE), {}),
        "a bar early from 02-09": (moved(bars, -MINUTE, date(2026, 2, 9)), {}),
        "hours off": (bars, {"time_zone": "America/Chicago"}),
    }
    file_bars, changes = files[case]
    request = request_of(exported(tmp_path, file_bars), LEAVE_OUT, **changes)

    preview = previewed(request)

    assert len(preview.reading.calendar.offsets) == 1
    assert preview.reading.calendar.breaks_with_bars == ()
    assert preview.reading.left_out is None
    assert preview.refusals() == [preview.reading.calendar.offsets[0].describe()]
    assert preview.summary().splitlines()[-1] == REFUSED_TO_FIX
    with pytest.raises(ValueError, match="offset: its records run") as refused:
        imported(request)
    assert "--bars-in-breaks" not in str(refused.value)


def thin_sessions_a_bar_early(sessions: SessionTable) -> pl.DataFrame:
    """A week of thin sessions, each its regular hours, Monday's after a print at its open and
    the others' after one at 17:20, as a file stamped at the bars' opens, read as their closes,
    gives: one bar early, Monday's open print in the break before it the only sign."""
    week = sessions.between(date(2026, 2, 2), date(2026, 2, 6)).select("trade_date", "open").rows()
    opens = [
        opened - MINUTE
        for trade_date, start in week
        for opened in [
            start if trade_date == FIRST else start + 20 * MINUTE,
            *range(start + 930 * MINUTE, start + 1320 * MINUTE, MINUTE),
        ]
    ]
    return pl.DataFrame({"ts_open": opens}, schema={"ts_open": pl.Int64}).with_columns(
        ts_close=pl.col("ts_open") + MINUTE,
        open=pl.lit(5_000_250_000_000),
        high=pl.lit(5_000_500_000_000),
        low=pl.lit(5_000_000_000_000),
        close=pl.lit(5_000_250_000_000),
        volume=pl.lit(10, dtype=pl.UInt64),
    )


def test_a_thin_file_a_bar_early_is_offered_no_correction(
    tmp_path: Path, sessions: SessionTable
) -> None:
    # From the review of the rule (D-104): without Monday the calendar cannot test the timing
    # of what remains, which runs a bar early, so the file is refused under both choices and
    # nothing offers to leave Monday out.
    path = exported(tmp_path, thin_sessions_a_bar_early(sessions))

    as_read = previewed(request_of(path))
    told = previewed(request_of(path, LEAVE_OUT))

    assert as_read.reading.calendar.offsets == ()
    assert len(as_read.reading.calendar.breaks_with_bars) == 1
    assert not as_read.reading.only_bars_in_breaks_refuse()
    assert as_read.summary().splitlines()[-1] == REFUSED_TO_FIX
    assert told.reading.left_out is None
    for preview in (as_read, told):
        (why,) = [refusal for refusal in preview.refusals() if "not to be left out" in refusal]
        assert "the calendar could not check the time zone and bar stamping" in why


def test_a_file_of_several_contracts_is_offered_no_correction(
    tmp_path: Path, bars: pl.DataFrame, sessions: SessionTable
) -> None:
    # Engine review, finding 3 (D-104): the calendar checks a file's contracts together, so the
    # records one contract leaves could hide another's offset. The correction applies to a file
    # of one contract alone: this Databento file of ESH2026, a bar in every minute of the break
    # after Wednesday, and ESM2026 is refused under both choices.
    path = written_export(
        tmp_path,
        "glbx-mdp3-20260202-20260213.ohlcv-1m.csv",
        databento_lines(
            ("ESH6", with_the_break_after(bars, WEDNESDAY, sessions)),
            ("ESM6", minutes_of(ESM2026, sessions.between(FIRST, LAST))),
        ),
    )

    for choice in BarsInBreaks:
        preview = previewed(
            FileImportRequest(path=path, profile=PRESETS["databento-csv"], bars_in_breaks=choice)
        )
        assert len(preview.reading.calendar.breaks_with_bars) == 1
        assert preview.reading.left_out is None
        assert not preview.reading.only_bars_in_breaks_refuse()
        (why,) = [refusal for refusal in preview.refusals() if "not to be left out" in refusal]
        assert "the file holds 2 contracts" in why


def test_a_file_whose_sessions_all_lie_beside_such_a_break_is_offered_no_correction(
    tmp_path: Path, bars: pl.DataFrame, sessions: SessionTable
) -> None:
    # Tuesday, Wednesday, and Thursday alone, a bar in every minute of the break after
    # Wednesday and a stray in the break after Tuesday, which joins Tuesday to the sessions
    # beside: they hold every record, so nothing is left to import, and the file is refused
    # under both choices.
    days = bars.filter(beside(TUESDAY, WEDNESDAY, THURSDAY))
    stray = (
        days.filter(pl.col("trade_date") == TUESDAY)
        .tail(1)
        .with_columns(pl.col("ts_open") + 6 * MINUTE, pl.col("ts_close") + 6 * MINUTE)
    )
    path = exported(tmp_path, with_the_break_after(pl.concat([days, stray]), WEDNESDAY, sessions))

    for choice in BarsInBreaks:
        preview = previewed(request_of(path, choice))
        assert preview.reading.left_out is None
        (why,) = [refusal for refusal in preview.refusals() if "not to be left out" in refusal]
        assert why.endswith("the sessions beside them hold every record of the file")


def test_told_to_leave_them_out_a_file_without_them_is_refused(
    tmp_path: Path, bars: pl.DataFrame
) -> None:
    # Under the choice a file without such a break is refused, so that the raw manifest records
    # the choice only where sessions were left out.
    preview = previewed(request_of(exported(tmp_path, bars), LEAVE_OUT))

    assert preview.reading.left_out is None
    assert preview.refusals() == [
        "ninjatrader/ohlcv-1m/root=ES no bars in a break: the file holds no break with a bar "
        "closing at the next open, whose sessions --bars-in-breaks leave-out would leave out, so "
        "import it without the option"
    ]


def test_no_price_reaches_what_an_import_says_of_its_bars_in_a_break(
    tmp_path: Path, bars: pl.DataFrame, sessions: SessionTable
) -> None:
    # D-21: the refusal, the reading, and the report of the import that left them out say what
    # they left out in counts and trade dates, none of the prices of the records left out.
    filled = with_the_break_after(bars, WEDNESDAY, sessions)
    path = exported(tmp_path, filled)
    with pytest.raises(ValueError) as refused:
        imported(request_of(path))
    report = imported(request_of(path, LEAVE_OUT))
    left_out = filled.filter(beside(WEDNESDAY, THURSDAY))
    prices: Iterable[int] = (
        left_out.select("open", "high", "low", "close").unpivot().get_column("value")
    )

    assert isinstance(report, FileImportReport)
    assert report.reading.left_out is not None
    texts = [str(refused.value), report.summary(), report.reading.left_out.model_dump_json()]
    assert priced(texts, set(prices)) == []
