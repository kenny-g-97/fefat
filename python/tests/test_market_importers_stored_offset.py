"""Records a file holds that are the stored ones at another offset (step 5.16, ADR-0024, Done
means 1): a file read an hour or a bar off whose timing the calendar cannot test, bars of regular
hours or prints of a few minutes, lands on the stored instants and reads as differing, or beside
them as new, and is refused whatever the import is told, in its preview too; a file that revises
a few of the stored records, or shares a few with them by chance, is not. The bars are ESH2026's
of ten sessions from the tests' generator, a walk of up to four ticks a minute, or made up in the
test with a price of their own each; the prints are made up from their seconds and places."""

import os
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from databento_dbn import OHLCVMsg

from dbn_files import utc
from export_samples import IMPORTED_ON, PRESETS, written_export
from fefat.config import resolve_paths
from fefat.market import instruments
from fefat.market.calendar import SessionTable, sessions_of
from fefat.market.importers.databento import import_databento
from fefat.market.importers.file_import import FileImportRequest, import_file, preview_file
from fefat.market.importers.file_report import AlreadyImported, FileImportReport, FilePreview
from fefat.market.importers.partition_merge import DifferingRecords
from fefat.market.importers.profiles import BarStamp
from fefat.market.importers.stored_offset import misread_offsets
from fefat.market.layout import Dataset
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import parse_schema_name, polars_schema
from fefat.market.store import Store
from generated_minutes import minutes_of
from test_market_importers_break_bars import ESH2026, FIRST, LAST, TUESDAY, exported, request_of
from test_market_importers_merge_properties import (
    ONE_MINUTE,
    SECOND_STAMPED_PRINTS,
    march_file,
    tree,
)
from test_market_importers_partition_buffers import (
    MINUTE_BARS,
    in_march,
    tallied,
)
from test_market_importers_partition_buffers import imported as stored_in

SECOND = 1_000_000_000
MINUTE = 60 * SECOND
HOUR = 60 * MINUTE
TICK = 250_000_000
FIVE_THOUSAND = 5_000_000_000_000
REFUSE, TAKE_THE_FILE = DifferingRecords.REFUSE, DifferingRecords.TAKE_THE_FILE
REGULAR_HOURS = (14 * HOUR + 30 * MINUTE, 21 * HOUR)
"""08:30 to 15:00 Chicago in February, as times of a UTC day."""
OPEN_STAMPED = PRESETS["ninjatrader"].model_copy(
    update={
        "name": "ninjatrader-at-the-open",
        "timestamp": PRESETS["ninjatrader"].timestamp.model_copy(update={"stamp": BarStamp.OPEN}),
    }
)
"""NinjaTrader's layout read as stamping each bar at its open, which NinjaTrader stamps at its
close: every bar a minute late."""
MONDAY = date(2026, 3, 30)
MONDAY_OPEN = utc(2026, 3, 29, 22)
"""The open of the session of 2026-03-30, 17:00 Chicago the evening before, in daylight time."""


@pytest.fixture
def sessions() -> SessionTable:
    calendar = instruments.get("ES").session_calendar()
    return sessions_of(calendar, resolve_paths(os.environ).cache_dir)


@pytest.fixture
def regular(sessions: SessionTable) -> pl.DataFrame:
    """ESH2026's bars of regular hours, 08:30 to 15:00 Chicago, of the ten sessions: moved by an
    hour or a bar they still fit their sessions, so the calendar cannot test their timing."""
    bars = minutes_of(ESH2026, sessions.between(FIRST, LAST))
    time_of_day = pl.col("ts_open") % (24 * HOUR)
    return bars.filter(time_of_day.is_between(*REGULAR_HOURS, closed="left"))


def the_store() -> Store:
    return Store(resolve_paths(os.environ).data_dir)


def previewed(request: FileImportRequest, differing: DifferingRecords) -> FilePreview:
    store = the_store()
    cache = resolve_paths(os.environ).cache_dir
    return preview_file(request, store, instrument_table(store.folder), cache, differing=differing)


def imported(
    request: FileImportRequest, differing: DifferingRecords = REFUSE
) -> FileImportReport | AlreadyImported:
    store = the_store()
    return import_file(
        request,
        store,
        resolve_paths(os.environ).cache_dir,
        imported_on=IMPORTED_ON,
        instruments=instrument_table(store.folder),
        differing=differing,
    )


@pytest.mark.parametrize("differing", list(DifferingRecords))
def test_bars_read_an_hour_early_are_refused_as_the_stored_ones_whatever_the_import_is_told(
    tmp_path: Path, regular: pl.DataFrame, differing: DifferingRecords
) -> None:
    # Done means 1: read as Berlin's time, the export's UTC stamps run an hour early. Its bars
    # land on the stored minutes and read as differing, which take-file took, or before the
    # first of them as new; the calendar cannot test regular hours, so only the store tells.
    imported(request_of(exported(tmp_path / "first", regular)))
    before = tree(the_store().folder)
    berlin = request_of(exported(tmp_path / "again", regular.head(-1)), time_zone="Europe/Berlin")
    refusal = r"equal to the stored records 1 hour later, on 10 trade dates from 2026-02-02"

    with pytest.raises(ValueError, match=refusal):
        previewed(berlin, differing)
    with pytest.raises(ValueError, match=refusal):
        imported(berlin, differing)

    assert tree(the_store().folder) == before


def test_bars_read_a_bar_late_are_refused_as_the_stored_ones_where_the_files_stand(
    tmp_path: Path, regular: pl.DataFrame
) -> None:
    # A profile that stamps NinjaTrader's bars at their open puts each a minute late.
    imported(request_of(exported(tmp_path / "first", regular)))
    before = tree(the_store().folder)
    again = exported(tmp_path / "again", regular.head(-1))
    late = FileImportRequest(path=again, profile=OPEN_STAMPED)

    with pytest.raises(ValueError, match="equal to the stored records 1 minute earlier"):
        imported(late, TAKE_THE_FILE)

    assert tree(the_store().folder) == before


def test_a_thin_export_read_an_hour_early_onto_minutes_the_store_lacks_is_refused(
    tmp_path: Path, regular: pl.DataFrame
) -> None:
    # The plan measured a thin month of the builder's MGC moved an hour late: 106 of its 107
    # bars land on minutes the store lacks, and one on a bar of the same values an hour away, as
    # a quiet hour gives, so that the file shares a bar with the store and merged by default.
    # Two minutes in a row of every eleven: an hour away from them lies none of them, and the
    # import sees minute bars, which it would not in bars a few minutes apart.
    thin = regular.filter(pl.int_range(pl.len()) % 11 < 2)
    quiet = thin.head(1).with_columns(pl.col("ts_open") + HOUR, pl.col("ts_close") + HOUR)
    stored = pl.concat([thin, quiet]).sort("ts_open")
    imported(request_of(exported(tmp_path / "first", stored)))
    before = tree(the_store().folder)
    berlin = request_of(exported(tmp_path / "again", stored.head(-1)), time_zone="Europe/Berlin")

    with pytest.raises(ValueError, match="equal to the stored records 1 hour later"):
        imported(berlin)

    assert tree(the_store().folder) == before


def distinct_bars(*opens: int, base: int = 27_000) -> list[OHLCVMsg]:
    """One-minute bars of ESH2026 opening at `opens`, each priced on its own: `base` ticks and
    its place among them."""
    return [
        OHLCVMsg(ONE_MINUTE, 1, 1001, opened, price, price + TICK, price - TICK, price, 10)
        for place, opened in enumerate(opens)
        for price in [TICK * (base + place)]
    ]  # fmt: skip


def test_a_databento_file_of_the_stored_bars_a_minute_later_is_refused(tmp_path: Path) -> None:
    store, cache = Store(tmp_path / "data"), tmp_path / "cache"
    opens = [utc(2026, 3, 9, 14, 30) + minute * MINUTE for minute in range(30)]
    import_databento(
        march_file(tmp_path, "first", distinct_bars(*opens)), store, cache, imported_on=IMPORTED_ON
    )
    before = tree(store.folder)
    later = march_file(tmp_path, "later", distinct_bars(*(opened + MINUTE for opened in opens)))

    with pytest.raises(ValueError, match="equal to the stored records 1 minute earlier"):
        import_databento(later, store, cache, imported_on=IMPORTED_ON, differing=TAKE_THE_FILE)

    assert tree(store.folder) == before


def prints_of(start: int, seconds: int, seed: int = 0) -> list[tuple[int, int, int]]:
    """Prints of `seconds` seconds in a row from `start`, one to three a second, each priced
    from its second, its place, and `seed`, and sized by its place: `(instant, price, size)`."""
    return [
        (
            start + second * SECOND,
            FIVE_THOUSAND + TICK * ((seed + second * 7_919 + place * 104_729) % 4_001),
            1 + place,
        )
        for second in range(seconds)
        for place in range(1 + second % 3)
    ]


def prints_export(
    folder: Path,
    prints: Sequence[tuple[int, int, int]],
    moved_by: int = 0,
    contract: str = "ESH2026",
) -> Path:
    """`prints` as a file of the contract's prints stamped to the second writes them, each
    `moved_by` later, as a platform's stamps in another time zone read as UTC give."""
    lines = [
        f"{(instant + moved_by) // SECOND},{Decimal(price) / SECOND},{size}"
        for instant, price, size in prints
    ]
    return written_export(folder, f"{contract}-prints.csv", ["time,price,size", *lines])


def imported_prints(
    path: Path, differing: DifferingRecords = REFUSE
) -> FileImportReport | AlreadyImported:
    return imported(FileImportRequest(path=path, profile=SECOND_STAMPED_PRINTS), differing)


def test_prints_read_an_hour_late_onto_seconds_the_store_lacks_are_refused(
    tmp_path: Path, sessions: SessionTable
) -> None:
    # Prints are compared by their place in their second, as the merge tells them apart.
    stored = prints_of(sessions.session(TUESDAY).open + 10 * MINUTE, 30)
    imported_prints(prints_export(tmp_path / "first", stored))
    before = tree(the_store().folder)

    with pytest.raises(ValueError, match="equal to the stored records 1 hour earlier"):
        imported_prints(prints_export(tmp_path / "later", stored, HOUR))

    assert tree(the_store().folder) == before


def test_prints_read_an_hour_late_onto_stored_seconds_are_refused_for_the_offset_first(
    tmp_path: Path, sessions: SessionTable
) -> None:
    # The design review of the plan: the file disputes its first second, as a file misread
    # disputes every one, and that refusal's advice, to start the file a second earlier, would
    # never let it in; the offset is what to fix.
    start = sessions.session(TUESDAY).open + 10 * MINUTE
    first_hour = prints_of(start, 20)
    imported_prints(
        prints_export(tmp_path / "first", [*first_hour, *prints_of(start + HOUR, 20, 9)])
    )
    before = tree(the_store().folder)

    with pytest.raises(ValueError, match="equal to the stored records 1 hour earlier"):
        imported_prints(prints_export(tmp_path / "later", first_hour, HOUR), TAKE_THE_FILE)

    assert tree(the_store().folder) == before


def test_prints_read_nine_hours_late_are_refused_by_the_trade_date_they_came_from(
    tmp_path: Path,
) -> None:
    # The design review of the plan: prints of 09:00 Chicago read nine hours late fall at 18:00,
    # in the next trade date's session, so the file's partition is new to the store, and the
    # prints it holds are the stored ones of the trade date before.
    stored = prints_of(utc(2026, 2, 3, 15), 30)
    imported_prints(prints_export(tmp_path / "first", stored))
    before = tree(the_store().folder)
    refusal = "equal to the stored records 9 hours earlier, on 1 trade date from 2026-02-04"

    with pytest.raises(ValueError, match=refusal):
        imported_prints(prints_export(tmp_path / "later", stored, 9 * HOUR))

    assert tree(the_store().folder) == before


def session_bars(*minutes: int, base: int = 1_000, trade_count: int | None = None) -> pl.DataFrame:
    """One-minute bars of 2026-03-30's session `minutes` after its open, each priced on its own:
    `base` ticks and its minute; with a trade count and a vwap where `trade_count` is given."""
    closes = [TICK * (base + minute) for minute in minutes]
    count = len(minutes)
    return pl.DataFrame(
        {
            "ts_open": [MONDAY_OPEN + minute * MINUTE for minute in minutes],
            "ts_close": [MONDAY_OPEN + (minute + 1) * MINUTE for minute in minutes],
            "trade_date": [MONDAY] * count,
            "instrument_id": [1001] * count,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1] * count,
            "trade_count": [trade_count] * count,
            "vwap": [None if trade_count is None else close for close in closes],
        },
        schema=polars_schema(MINUTE_BARS),
    )


def moved(bars: pl.DataFrame, nanoseconds: int) -> pl.DataFrame:
    """`bars`, each `nanoseconds` later."""
    return bars.with_columns(pl.col("ts_open") + nanoseconds, pl.col("ts_close") + nanoseconds)


def test_bars_new_to_the_store_that_are_its_bars_an_hour_away_refuse_a_file_from_ten(
    tmp_path: Path,
) -> None:
    # The floor: one bar the store took before it was complete, the routine reason to take a
    # file, is never ten, while a thin month of the builder's read an hour off held a hundred.
    store = Store(tmp_path)
    stored_in(store, in_march(session_bars(*range(30))))
    refusal = (
        "got 10 of the 10 compared equal to the stored records 1 hour earlier, on 1 trade date "
        "from 2026-03-30"
    )

    (nine,) = tallied(store, in_march(moved(session_bars(*range(9)), HOUR)), REFUSE)
    with pytest.raises(ValueError, match=refusal):
        tallied(store, in_march(moved(session_bars(*range(10)), HOUR)), REFUSE)

    assert nine.records_added == 9


def test_bars_fifteen_hours_off_are_refused_as_the_stored_ones(tmp_path: Path) -> None:
    # Two time zones lie up to 26 hours apart, Chicago's and Tokyo's 15 in winter, where the
    # calendar check looks for 14 at most, since its sessions repeat each day.
    store = Store(tmp_path)
    stored_in(store, in_march(session_bars(*range(30))))

    with pytest.raises(ValueError, match="equal to the stored records 15 hours earlier"):
        tallied(store, in_march(moved(session_bars(*range(30)), 15 * HOUR)), REFUSE)


def test_bars_one_import_counted_the_trades_of_are_compared_without_the_count(
    tmp_path: Path,
) -> None:
    # The design review of the plan: a profile that maps a trade count and a vwap, and a copy
    # of it that does not, give the same bars other columns, and every bar of a misread file
    # differed in them from the stored one at its offset.
    store = Store(tmp_path)
    stored_in(store, in_march(session_bars(*range(30), trade_count=5)))

    with pytest.raises(ValueError, match="equal to the stored records 1 hour earlier"):
        tallied(store, in_march(moved(session_bars(*range(30)), HOUR)), REFUSE)


def test_a_revision_of_a_dozen_stored_bars_is_taken_where_the_files_stand(tmp_path: Path) -> None:
    store = Store(tmp_path)
    stored_in(store, in_march(session_bars(*range(30))))
    revised = pl.concat(
        [
            session_bars(*range(5)),
            session_bars(*range(5, 17), base=5_000),
            session_bars(*range(17, 30)),
        ]
    )

    (merge,) = tallied(store, in_march(revised), TAKE_THE_FILE)

    assert (merge.records_held, merge.records_differing) == (18, 12)


def test_bars_a_few_of_which_are_the_stored_ones_a_minute_away_by_chance_are_taken(
    tmp_path: Path,
) -> None:
    # Eighteen of 1,000 revised bars equal the stored bar a minute before, as a quiet market
    # gives now and then: under half of those beside which the store holds a bar there.
    store = Store(tmp_path)
    stored_in(store, in_march(session_bars(*range(1_000))))
    by_chance = range(50, 950, 50)
    others = [minute for minute in range(1_000) if minute not in by_chance]
    revised = pl.concat(
        [session_bars(*by_chance, base=999), session_bars(*others, base=9_000)]
    ).sort("ts_open")

    (merge,) = tallied(store, in_march(revised), TAKE_THE_FILE)

    assert merge.records_differing == 1_000


@pytest.mark.parametrize(
    ("schema", "offsets", "farthest"),
    [
        ("ohlcv-1m", 314, 26 * HOUR + MINUTE),
        ("trades", 104, 26 * HOUR),
        ("tbbo", 104, 26 * HOUR),
        ("ohlcv-1d", 0, None),
        ("funding", 0, None),
        ("definitions", 0, None),
    ],
)
def test_a_misread_file_is_compared_at_half_hours_and_a_bar_up_to_26_hours_off(
    schema: str, offsets: int, farthest: int | None
) -> None:
    # Daily bars are dated by the date they name, which no time zone moves, and a funding rate
    # often repeats the one eight hours before.
    found = misread_offsets(
        Dataset(provider="ibkr", schema_name=parse_schema_name(schema), root="ES")
    )

    assert len(found) == offsets
    assert max(found, default=None) == farthest
    assert found == tuple(sorted(found)) and 0 not in found
