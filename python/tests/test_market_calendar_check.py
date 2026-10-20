import shutil
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from fefat.market.builtin_calendars import BUILT_IN
from fefat.market.calendar import Session, SessionTable, sessions_of, utc_text
from fefat.market.calendar_check import (
    CalendarReport,
    MismatchKind,
    MissingSession,
    SessionMismatch,
    SessionWithoutPrints,
    check_records,
    validate_calendar,
)
from fefat.market.calendar_definition import CalendarId
from fefat.market.calendar_offset import CalendarOffset, OffsetCause
from fefat.market.layout import (
    Dataset,
    DatasetMetadata,
    DatasetOrigin,
    Partition,
    PartitionRequest,
    SizeUnit,
    YearMonth,
)
from fefat.market.schema import parse_schema_name, polars_schema
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
ES_TRADES = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES")
ES_SECONDS = Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1s"), root="ES")
ES_MINUTES = Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES")
ES_FIXTURE_DAYS = (date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9))
HOUR = 3_600 * 1_000_000_000
NO_LICENCE = "Synthetic test data; no licence applies"


def utc(*fields: int) -> int:
    year, month, day, *clock = fields
    return int(datetime(year, month, day, *clock, tzinfo=UTC).timestamp()) * 1_000_000_000


def first_and_last(frame: pl.DataFrame, first: str, last: str) -> tuple[int, int]:
    """The smallest `first` and the largest `last` of the frame."""
    return frame.select(first=pl.col(first).min(), last=pl.col(last).max()).row(0)


def copied_fixtures(folder: Path) -> Store:
    """The fixtures with one ES contract, ESH2026, so that each edit of a test decides the
    first and last prints of its root's trade dates."""
    shutil.copytree(
        FIXTURES / "synthetic",
        folder / "synthetic",
        ignore=shutil.ignore_patterns("contract=ESM2026"),
    )
    return Store(folder)


MARCH_6 = date(2026, 3, 6)
MARCH_6_SESSION = Session(trade_date=MARCH_6, open=utc(2026, 3, 5, 23), close=utc(2026, 3, 6, 22))


def after_the_close_of_march_6(store: Store) -> tuple[SessionMismatch, ...]:
    """The fixtures' own mismatches in `store`: the print planted 400 ms after the close of
    ESH2026's Friday 2026-03-06 keeps that trade date (step 1.5), so its trades, and its
    1-second and 1-minute bars opening at the close, print after the close; the first print is
    the earliest of the root's contracts."""
    found = []
    for dataset, first_column, last_column in (
        (ES_MINUTES, "ts_open", "ts_close"),
        (ES_SECONDS, "ts_open", "ts_close"),
        (ES_TRADES, "ts_recv", "ts_recv"),
    ):
        rows = store.scan(PartitionRequest(dataset=dataset, start=MARCH_6, end=MARCH_6))
        found.append((dataset, *first_and_last(rows.collect(), first_column, last_column)))
    return tuple(
        SessionMismatch(
            dataset=dataset,
            trade_date=MARCH_6,
            kind=MismatchKind.PRINT_AFTER_CLOSE,
            first_print=first,
            last_print=last,
            session=MARCH_6_SESSION,
        )
        for dataset, first, last in found
    )


def test_the_synthetic_fixtures_match_their_calendars_but_for_a_print_after_a_close(
    tmp_path: Path,
) -> None:
    # ES trades, 1-second bars, and 1-minute bars of two contracts on three trade dates, and
    # the same three schemas of BTCUSDT-PERP on one UTC day. The print ESH2026 received 400 ms
    # after the close of 2026-03-06, at 22:00 UTC, ends that day's trades, a 1-second bar, and
    # a 1-minute bar.
    report = validate_calendar(Store(FIXTURES), tmp_path)

    mismatches = after_the_close_of_march_6(Store(FIXTURES))
    assert report == CalendarReport(days_checked=12, mismatches=mismatches)
    assert [mismatch.last_print for mismatch in mismatches] == [
        utc(2026, 3, 6, 22, 1),
        utc(2026, 3, 6, 22, 0, 1),
        utc(2026, 3, 6, 22) + 400_000_000,
    ]
    assert report.summary().splitlines()[0] == "Trade dates checked: 12. Mismatches: 3."


def test_ticks_filed_under_another_trade_date_are_reported_with_their_times(
    tmp_path: Path,
) -> None:
    store = copied_fixtures(tmp_path / "store")
    trades = store.scan_partition(
        Partition(dataset=ES_TRADES, contract="ESH2026", key=date(2026, 3, 6))
    ).collect()
    store.write_partition(
        Partition(dataset=ES_TRADES, contract="ESH2026", key=date(2026, 3, 10)), trades
    )
    first, last = first_and_last(trades, "ts_recv", "ts_recv")
    # The March 6 trades lie from 2026-03-05 23:00 UTC to just before 2026-03-06 22:00 UTC,
    # while Tuesday 03-10's session runs from Monday 17:00 CDT, 22:00 UTC, to 16:00 CDT, 21:00
    # UTC: the first print comes before the open and the last long before the close.
    session = Session(
        trade_date=date(2026, 3, 10), open=utc(2026, 3, 9, 22), close=utc(2026, 3, 10, 21)
    )

    report = validate_calendar(store, tmp_path / "cache")

    assert report.days_checked == 13
    assert report.mismatches == (
        *after_the_close_of_march_6(store),
        *(
            SessionMismatch(
                dataset=ES_TRADES,
                trade_date=date(2026, 3, 10),
                kind=kind,
                first_print=first,
                last_print=last,
                session=session,
            )
            for kind in (MismatchKind.EARLY_LAST_PRINT, MismatchKind.PRINT_BEFORE_OPEN)
        ),
    )
    assert report.summary().splitlines()[4] == (
        f"synthetic/trades/root=ES 2026-03-10 early-last-print: prints {utc_text(first)} to "
        f"{utc_text(last)}, session 2026-03-09T22:00:00Z to 2026-03-10T21:00:00Z"
    )


def test_bars_on_a_day_without_a_session_are_reported(tmp_path: Path) -> None:
    # Juneteenth 2026 trades until a midday halt but has no trade date of its own. The store
    # holds only these bars, so no session between the fixtures' March and June lacks prints.
    fixtures = Store(FIXTURES)
    march_9 = Partition(dataset=ES_SECONDS, contract="ESH2026", key=date(2026, 3, 9))
    juneteenth = date(2026, 6, 19)
    bars = fixtures.scan_partition(march_9).collect().with_columns(trade_date=pl.lit(juneteenth))
    store = Store(tmp_path / "store")
    store.write_dataset_metadata(ES_SECONDS, fixtures.dataset_metadata(ES_SECONDS))
    store.write_partition(Partition(dataset=ES_SECONDS, contract="ESH2026", key=juneteenth), bars)
    first, last = first_and_last(bars, "ts_open", "ts_close")

    report = validate_calendar(store, tmp_path / "cache")

    assert report.mismatches == (
        MissingSession(
            dataset=ES_SECONDS, trade_date=juneteenth, first_print=first, last_print=last
        ),
    )
    assert report.summary().splitlines() == [
        "Trade dates checked: 1. Mismatches: 1.",
        f"synthetic/ohlcv-1s/root=ES 2026-06-19 no-session: prints {utc_text(first)} to "
        f"{utc_text(last)}, on a day without a session",
    ]


def test_bars_an_hour_late_open_late_and_print_after_the_close(tmp_path: Path) -> None:
    store = copied_fixtures(tmp_path / "store")
    month = Partition(dataset=ES_MINUTES, contract="ESH2026", key=YearMonth(year=2026, month=3))
    late = (
        store.scan_partition(month)
        .collect()
        .with_columns(pl.col("ts_open") + HOUR, pl.col("ts_close") + HOUR)
    )
    store.write_partition(month, late)

    report = validate_calendar(store, tmp_path / "cache")
    within_two_hours = validate_calendar(store, tmp_path / "cache", tolerance=timedelta(hours=2))

    assert {
        (mismatch.dataset, mismatch.trade_date, mismatch.kind) for mismatch in report.mismatches
    } == {
        (ES_MINUTES, day, kind)
        for day in ES_FIXTURE_DAYS
        for kind in (MismatchKind.LATE_FIRST_PRINT, MismatchKind.PRINT_AFTER_CLOSE)
    } | {(dataset, MARCH_6, MismatchKind.PRINT_AFTER_CLOSE) for dataset in (ES_SECONDS, ES_TRADES)}
    assert {mismatch.kind for mismatch in within_two_hours.mismatches} == {
        MismatchKind.PRINT_AFTER_CLOSE
    }
    assert report.offsets == (
        CalendarOffset(
            dataset=ES_MINUTES,
            nanoseconds=HOUR,
            cause=OffsetCause.TIME_ZONE,
            first_trade_date=ES_FIXTURE_DAYS[0],
            last_trade_date=ES_FIXTURE_DAYS[-1],
        ),
    )


def test_a_root_without_a_known_calendar_is_refused(tmp_path: Path) -> None:
    store = copied_fixtures(tmp_path / "store")
    unknown = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ZZ")
    store.write_dataset_metadata(
        unknown,
        DatasetMetadata(
            size_unit=SizeUnit(lot=Decimal(1), asset="contract"),
            origin=DatasetOrigin.IMPORT,
            licence_scope=NO_LICENCE,
        ),
    )
    trades = store.scan_partition(
        Partition(dataset=ES_TRADES, contract="ESH2026", key=date(2026, 3, 9))
    ).collect()
    store.write_partition(
        Partition(dataset=unknown, contract="ZZH2026", key=date(2026, 3, 9)), trades
    )

    with pytest.raises(ValueError, match="Expected a root of the instrument table"):
        validate_calendar(store, tmp_path / "cache")


def test_a_coarse_bar_that_straddles_an_early_close_is_not_a_print_after_it(
    tmp_path: Path,
) -> None:
    # The day after Thanksgiving 2025, equity index opens on Wednesday at 17:00 CST, 23:00 UTC,
    # and closes early at 12:15 CST, 18:15 UTC. An hourly bar from 12:00 to 13:00 CST, 18:00 to
    # 19:00 UTC, holds prints from before the close, so it ends after the close without being
    # a print after it.
    store = Store(tmp_path / "store")
    hours = Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1h"), root="ES")
    store.write_dataset_metadata(
        hours,
        DatasetMetadata(
            size_unit=SizeUnit(lot=Decimal(1), asset="contract"),
            origin=DatasetOrigin.IMPORT,
            licence_scope=NO_LICENCE,
        ),
    )
    bars = pl.DataFrame(
        {
            "ts_open": [utc(2025, 11, 26, 23), utc(2025, 11, 28, 18)],
            "ts_close": [utc(2025, 11, 27), utc(2025, 11, 28, 19)],
            "trade_date": [date(2025, 11, 28), date(2025, 11, 28)],
            "instrument_id": [1001, 1001],
            "open": [1, 1],
            "high": [1, 1],
            "low": [1, 1],
            "close": [1, 1],
            "volume": [1, 1],
            "trade_count": [1, 1],
            "vwap": [1, 1],
        },
        schema=polars_schema(hours.schema_name),
    )
    store.write_partition(Partition(dataset=hours, contract="ESZ2025", key=None), bars)

    report = validate_calendar(store, tmp_path / "cache")

    assert report == CalendarReport(days_checked=1, mismatches=())


def test_a_session_without_prints_inside_a_datasets_dates_is_reported(tmp_path: Path) -> None:
    # With Friday 2026-03-06 gone from every ES dataset, its session, from Thursday 17:00 CST,
    # 23:00 UTC, to 16:00 CST, 22:00 UTC, has no prints between the first trade date, 03-05,
    # and the last, 03-09: the trace of a day the vendor missed, or of a full close the
    # calendar lacks.
    store = copied_fixtures(tmp_path / "store")
    friday = date(2026, 3, 6)
    for dataset in (ES_TRADES, ES_SECONDS):
        partition = Partition(dataset=dataset, contract="ESH2026", key=friday)
        (tmp_path / "store" / partition.relative_path()).unlink()
    month = Partition(dataset=ES_MINUTES, contract="ESH2026", key=YearMonth(year=2026, month=3))
    others = store.scan_partition(month).collect().filter(pl.col("trade_date") != friday)
    store.write_partition(month, others)
    session = Session(trade_date=friday, open=utc(2026, 3, 5, 23), close=utc(2026, 3, 6, 22))

    report = validate_calendar(store, tmp_path / "cache")

    assert report.days_checked == 12
    assert report.mismatches == tuple(
        SessionWithoutPrints(dataset=dataset, trade_date=friday, session=session)
        for dataset in (ES_MINUTES, ES_SECONDS, ES_TRADES)
    )
    assert report.summary().splitlines()[1] == (
        "synthetic/ohlcv-1m/root=ES 2026-03-06 no-prints: no prints in the session "
        "2026-03-05T23:00:00Z to 2026-03-06T22:00:00Z"
    )


def test_an_empty_tick_file_adds_no_trade_date(tmp_path: Path) -> None:
    # An empty file on Saturday 2026-03-07 adds nothing to check, and an empty file in place of
    # Friday 03-06's trades leaves that session without prints; its bars still end with the
    # print after the close.
    store = copied_fixtures(tmp_path / "store")
    empty = pl.DataFrame(schema=polars_schema(ES_TRADES.schema_name))
    for day in (date(2026, 3, 6), date(2026, 3, 7)):
        store.write_partition(Partition(dataset=ES_TRADES, contract="ESH2026", key=day), empty)

    report = validate_calendar(store, tmp_path / "cache")

    assert [
        (mismatch.dataset, mismatch.trade_date, mismatch.kind) for mismatch in report.mismatches
    ] == [
        (ES_MINUTES, MARCH_6, MismatchKind.PRINT_AFTER_CLOSE),
        (ES_SECONDS, MARCH_6, MismatchKind.PRINT_AFTER_CLOSE),
        (ES_TRADES, MARCH_6, MismatchKind.NO_PRINTS),
    ]


ESH2026_MINUTES = Partition(
    dataset=ES_MINUTES, contract="ESH2026", key=YearMonth(year=2026, month=3)
)
MINUTE = 60 * 1_000_000_000


def minute_bars_moved_by(nanoseconds: int, cache: Path) -> tuple[pl.LazyFrame, SessionTable]:
    """The fixtures' ESH2026 1-minute bars moved later by `nanoseconds`, dated again as an
    import dates them, beside the session table of their calendar."""
    sessions = sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], cache)
    bars = Store(FIXTURES).scan_partition(ESH2026_MINUTES).collect()
    moved = bars.drop("trade_date").with_columns(
        pl.col("ts_open") + nanoseconds, pl.col("ts_close") + nanoseconds
    )
    dated = sessions.assign_trade_dates_or_previous(moved, "ts_open")
    return dated.select(bars.columns).lazy(), sessions


def test_the_fixtures_bars_run_neither_late_nor_early(tmp_path: Path) -> None:
    bars, sessions = minute_bars_moved_by(0, tmp_path)

    assert check_records(ES_MINUTES, bars, sessions).offsets == ()


@pytest.mark.parametrize("hours", [6, 5, -6])
def test_bars_read_in_the_wrong_time_zone_show_its_offset_in_hours(
    tmp_path: Path, hours: int
) -> None:
    # UTC times read as Chicago's, CST until 2026-03-08, run 6 hours late on 03-05 and 03-06
    # and, once CDT starts, 5 on 03-09; the offset of most of the bars wins.
    bars, sessions = minute_bars_moved_by(hours * HOUR, tmp_path)

    report = check_records(ES_MINUTES, bars, sessions)

    assert report.offsets == (
        CalendarOffset(
            dataset=ES_MINUTES,
            nanoseconds=hours * HOUR,
            cause=OffsetCause.TIME_ZONE,
            first_trade_date=ES_FIXTURE_DAYS[0],
            last_trade_date=ES_FIXTURE_DAYS[-1],
        ),
    )
    direction = "late" if hours > 0 else "early"
    assert report.summary().splitlines()[1] == (
        f"synthetic/ohlcv-1m/root=ES offset: its records run {abs(hours)} hours {direction} "
        "against the calendar on the trade dates 2026-03-05 to 2026-03-09; check the time "
        "zone of the file's times"
    )


@pytest.mark.parametrize("minutes", [1, -1])
def test_bars_read_with_the_wrong_stamping_show_an_offset_of_one_bar(
    tmp_path: Path, minutes: int
) -> None:
    # A file that stamps each bar's close, read as its open, puts each session's last bar at
    # the close; a file that stamps the open, read as the close, puts each first bar in the
    # break before the open.
    bars, sessions = minute_bars_moved_by(minutes * MINUTE, tmp_path)

    assert check_records(ES_MINUTES, bars, sessions).offsets == (
        CalendarOffset(
            dataset=ES_MINUTES,
            nanoseconds=minutes * MINUTE,
            cause=OffsetCause.BAR_STAMPING,
            first_trade_date=ES_FIXTURE_DAYS[0],
            last_trade_date=ES_FIXTURE_DAYS[-1],
        ),
    )


def moved_on_march_9(nanoseconds: int, cache: Path) -> tuple[pl.LazyFrame, SessionTable]:
    """The fixtures' ESH2026 1-minute bars, those of the 03-09 session moved later by
    `nanoseconds`, dated again as an import dates them, beside their session table."""
    sessions = sessions_of(BUILT_IN[CalendarId.CME_EQUITY_INDEX], cache)
    bars = Store(FIXTURES).scan_partition(ESH2026_MINUTES).collect()
    shift = pl.when(pl.col("trade_date") == date(2026, 3, 9)).then(nanoseconds).otherwise(0)
    moved = bars.with_columns(pl.col("ts_open") + shift, pl.col("ts_close") + shift)
    dated = sessions.assign_trade_dates_or_previous(moved.drop("trade_date"), "ts_open")
    return dated.select(bars.columns).lazy(), sessions


def test_bars_an_hour_early_once_daylight_saving_starts_show_that_offset_from_then(
    tmp_path: Path,
) -> None:
    # Times in fixed standard time read as Chicago's run an hour early once CDT starts on
    # 2026-03-08: only the 03-09 session moves, too few bars for an offset of the whole file.
    bars, sessions = moved_on_march_9(-HOUR, tmp_path)

    report = check_records(ES_MINUTES, bars, sessions)

    assert [(offset.nanoseconds, offset.cause) for offset in report.offsets] == [
        (-HOUR, OffsetCause.TIME_ZONE)
    ]
    assert report.offsets[0].describe() == (
        "synthetic/ohlcv-1m/root=ES offset: its records run 1 hour early against the calendar "
        "on the trade date 2026-03-09; check the time zone of the file's times"
    )


def test_one_session_with_a_bar_in_the_break_before_its_open_shows_an_offset_of_one_bar(
    tmp_path: Path,
) -> None:
    # Nothing prints in the minute before an open, so one session whose bars run a bar early
    # shows the stamping.
    bars, sessions = moved_on_march_9(-MINUTE, tmp_path)

    report = check_records(ES_MINUTES, bars, sessions)

    assert [(offset.nanoseconds, offset.cause) for offset in report.offsets] == [
        (-MINUTE, OffsetCause.BAR_STAMPING)
    ]
