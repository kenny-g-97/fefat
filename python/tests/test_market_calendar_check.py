import shutil
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from fefat.market.calendar import Session, utc_text
from fefat.market.calendar_check import (
    CalendarReport,
    MismatchKind,
    MissingSession,
    SessionMismatch,
    SessionWithoutPrints,
    validate_calendar,
)
from fefat.market.layout import Dataset, DatasetMetadata, Partition, SizeUnit, YearMonth
from fefat.market.schema import parse_schema_name, polars_schema
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
ES_TRADES = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES")
ES_SECONDS = Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1s"), root="ES")
ES_MINUTES = Dataset(provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES")
ES_FIXTURE_DAYS = (date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 9))
HOUR = 3_600 * 1_000_000_000


def utc(*fields: int) -> int:
    year, month, day, *clock = fields
    return int(datetime(year, month, day, *clock, tzinfo=UTC).timestamp()) * 1_000_000_000


def first_and_last(frame: pl.DataFrame, first: str, last: str) -> tuple[int, int]:
    """The smallest `first` and the largest `last` of the frame."""
    return frame.select(first=pl.col(first).min(), last=pl.col(last).max()).row(0)


def copied_fixtures(folder: Path) -> Store:
    shutil.copytree(FIXTURES / "synthetic", folder / "synthetic")
    return Store(folder)


MARCH_6 = date(2026, 3, 6)
MARCH_6_SESSION = Session(trade_date=MARCH_6, open=utc(2026, 3, 5, 23), close=utc(2026, 3, 6, 22))


def after_the_close_of_march_6() -> tuple[SessionMismatch, ...]:
    """The fixtures' own mismatches: the print planted 400 ms after the close of ES's Friday
    2026-03-06 keeps that trade date (step 1.5), so its trades, and its 1-second and 1-minute
    bars opening at the close, print after the close."""
    store = Store(FIXTURES)
    found = []
    for dataset, key in ((ES_MINUTES, YearMonth(year=2026, month=3)), (ES_SECONDS, MARCH_6)):
        bars = store.scan_partition(Partition(dataset=dataset, contract="ESH2026", key=key))
        first, last = first_and_last(
            bars.filter(pl.col("trade_date") == MARCH_6).collect(), "ts_open", "ts_close"
        )
        found.append((dataset, first, last))
    trades = store.scan_partition(Partition(dataset=ES_TRADES, contract="ESH2026", key=MARCH_6))
    found.append((ES_TRADES, *first_and_last(trades.collect(), "ts_recv", "ts_recv")))
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
    # ES trades, 1-second bars, and 1-minute bars on three trade dates, and the same three
    # schemas of BTCUSDT-PERP on one UTC day. The print received 400 ms after the close of
    # 2026-03-06, at 22:00 UTC, ends that day's trades, a 1-second bar, and a 1-minute bar.
    report = validate_calendar(Store(FIXTURES), tmp_path)

    mismatches = after_the_close_of_march_6()
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
        *after_the_close_of_march_6(),
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


def test_a_root_without_a_known_calendar_is_refused(tmp_path: Path) -> None:
    store = copied_fixtures(tmp_path / "store")
    unknown = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ZZ")
    store.write_dataset_metadata(
        unknown, DatasetMetadata(size_unit=SizeUnit(lot=Decimal(1), asset="contract"))
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
        hours, DatasetMetadata(size_unit=SizeUnit(lot=Decimal(1), asset="contract"))
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
