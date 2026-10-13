import shutil
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from fefat.market.calendar import Session, utc_text
from fefat.market.calendar_check import (
    CalendarMismatch,
    CalendarReport,
    MismatchKind,
    validate_calendar,
)
from fefat.market.layout import Dataset, DatasetMetadata, Partition, SizeUnit, YearMonth
from fefat.market.schema import parse_schema_name
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


def test_the_synthetic_fixtures_match_their_calendars(tmp_path: Path) -> None:
    # ES trades, 1-second bars, and 1-minute bars on three trade dates, and the same three
    # schemas of BTCUSDT-PERP on one UTC day.
    report = validate_calendar(Store(FIXTURES), tmp_path)

    assert report == CalendarReport(days_checked=12, mismatches=())
    assert report.summary() == "No mismatches over 12 trade dates."


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
    assert report.mismatches == tuple(
        CalendarMismatch(
            dataset=ES_TRADES,
            trade_date=date(2026, 3, 10),
            kind=kind,
            first_print=first,
            last_print=last,
            session=session,
        )
        for kind in (MismatchKind.EARLY_LAST_PRINT, MismatchKind.PRINT_BEFORE_OPEN)
    )
    assert report.summary().splitlines()[1] == (
        f"synthetic/trades/root=ES 2026-03-10 early-last-print: prints {utc_text(first)} to "
        f"{utc_text(last)}, session 2026-03-09T22:00:00Z to 2026-03-10T21:00:00Z"
    )


def test_bars_on_a_day_without_a_session_are_reported(tmp_path: Path) -> None:
    store = copied_fixtures(tmp_path / "store")
    march_9 = Partition(dataset=ES_SECONDS, contract="ESH2026", key=date(2026, 3, 9))
    # Juneteenth 2026 trades until a midday halt but has no trade date of its own.
    juneteenth = date(2026, 6, 19)
    bars = store.scan_partition(march_9).collect().with_columns(trade_date=pl.lit(juneteenth))
    store.write_partition(Partition(dataset=ES_SECONDS, contract="ESH2026", key=juneteenth), bars)
    first, last = first_and_last(bars, "ts_open", "ts_close")

    report = validate_calendar(store, tmp_path / "cache")

    assert report.mismatches == (
        CalendarMismatch(
            dataset=ES_SECONDS,
            trade_date=juneteenth,
            kind=MismatchKind.NO_SESSION,
            first_print=first,
            last_print=last,
            session=None,
        ),
    )
    assert report.summary().splitlines() == [
        "Mismatches over 13 trade dates: 1",
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
    }
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
