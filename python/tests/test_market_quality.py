import shutil
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fefat.market.importers.databento import import_databento
from fefat.market.importers.report import ConditionDay, VendorCondition
from fefat.market.layout import Dataset, DatasetMetadata, Partition, SizeUnit, YearMonth
from fefat.market.quality import assess_quality
from fefat.market.quality_report import (
    DAY_COLUMNS,
    FINDING_COLUMNS,
    QualityReport,
    QualityStanding,
    QualityStatus,
    quality_standing,
    write_quality_report,
)
from fefat.market.schema import parse_schema_name, polars_schema
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Store(ROOT / "fixtures")
SYNTHETIC = ROOT / "fixtures" / "synthetic"
BATCH = SYNTHETIC / "databento-batch" / "GLBX-20260310-SYNTHETIC0"
MARCH_5, MARCH_6, MARCH_9 = (date(2026, 3, day) for day in (5, 6, 9))
DAY = 86_400_000_000_000
QUARTER_POINT = 250_000_000
CONTRACT_SIZES = DatasetMetadata(size_unit=SizeUnit(lot=Decimal(1), asset="contract"))

# Per session of ES in the fixtures: every record, the trades of both contracts, their
# 1-second and 1-minute bars, the prints in the break after the close (the trade received
# 400 ms after the close of 2026-03-06, kept with its trade date, with its 1-second and
# 1-minute bars), the prints inside a halt, the differences of the bars from the finer data,
# the vendor's condition (none for synthetic data), and the buckets held back.
CLEAN_DAYS = pl.DataFrame(
    [
        (MARCH_5, 139_570, 93_084, 43_752, 2_734, 0, 0, 0, None, 0),
        (MARCH_6, 250_706, 178_728, 69_217, 2_761, 3, 0, 0, None, 0),
        (MARCH_9, 170_130, 114_429, 52_941, 2_760, 0, 0, 0, None, 0),
    ],
    schema=DAY_COLUMNS,
    orient="row",
)


def utc(*fields: int) -> int:
    """The instant of a UTC date and time, in nanoseconds since the Unix epoch."""
    year, month, day, *clock = fields
    return int(datetime(year, month, day, *clock, tzinfo=UTC).timestamp()) * 1_000_000_000


def es(schema: str) -> Dataset:
    return Dataset(provider="synthetic", schema_name=parse_schema_name(schema), root="ES")


def es_trades(contract: str, day: date) -> Partition:
    return Partition(dataset=es("trades"), contract=contract, key=day)


def es_minutes(contract: str) -> Partition:
    return Partition(dataset=es("ohlcv-1m"), contract=contract, key=YearMonth(year=2026, month=3))


def copied_fixtures(folder: Path) -> Store:
    shutil.copytree(SYNTHETIC, folder / "synthetic")
    return Store(folder)


def rewrite(
    store: Store, partition: Partition, change: Callable[[pl.DataFrame], pl.DataFrame]
) -> None:
    store.write_partition(partition, change(store.scan_partition(partition).collect()))


def with_a_duplicate_and_a_print_a_day_late(trades: pl.DataFrame) -> pl.DataFrame:
    """The trades with the 101st repeated right after itself, which keeps the clock in order,
    and the first received again a day later at the end, inside the next session's hours."""
    a_day_late = trades.head(1).with_columns(pl.col("ts_recv", "ts_event") + DAY)
    return pl.concat([trades.head(101), trades.slice(100), a_day_late])


def with_two_neighbours_swapped(trades: pl.DataFrame) -> pl.DataFrame:
    """The trades with the first two neighbours received at different instants swapped: one
    decrease of the clock."""
    clock = trades.get_column("ts_recv")
    first = next(index for index in range(trades.height - 1) if clock[index] < clock[index + 1])
    swapped = [trades.slice(first + 1, 1), trades.slice(first, 1)]
    return pl.concat([trades.head(first), *swapped, trades.slice(first + 2)])


def crude_trades(instant: int, price: int, instrument_id: int) -> pl.DataFrame:
    return pl.DataFrame(
        [(instant, instant, instrument_id, price, 1, "B", 1)],
        schema=polars_schema(parse_schema_name("trades")),
        orient="row",
    )


@pytest.fixture(scope="module")
def cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("cache")


@pytest.fixture(scope="module")
def clean_report(cache: Path) -> QualityReport:
    return assess_quality(FIXTURES, "synthetic", "ES", cache)


def test_the_clean_fixtures_have_a_row_per_session_and_no_finding(
    clean_report: QualityReport,
) -> None:
    assert_frame_equal(clean_report.days, CLEAN_DAYS)
    assert clean_report.findings.is_empty()
    assert clean_report.status() is QualityStatus.CLEAN
    assert clean_report.contracts == ("ESH2026", "ESM2026")
    assert clean_report.summary() == "Quality of synthetic ES, 2026-03-05 to 2026-03-09: clean."


def test_the_report_finds_the_planted_anomalies_and_nothing_else(
    tmp_path: Path, cache: Path
) -> None:
    # Planted in a copy of the fixtures: a gap, both contracts' trades of 2026-03-06 deleted; a
    # duplicate and an out-of-session print in the trades of ESH2026 on 03-05; and a clock
    # decrease in the trades of ESM2026 on 03-09. A day whose records hold a finding is not
    # rebuilt from them, so the duplicate's volume shows in no bar.
    store = copied_fixtures(tmp_path)
    for contract in ("ESH2026", "ESM2026"):
        (tmp_path / es_trades(contract, MARCH_6).relative_path()).unlink()
    rewrite(store, es_trades("ESH2026", MARCH_5), with_a_duplicate_and_a_print_a_day_late)
    rewrite(store, es_trades("ESM2026", MARCH_9), with_two_neighbours_swapped)

    report = assess_quality(store, "synthetic", "ES", cache)

    expected = pl.DataFrame(
        [
            (MARCH_5, "duplicates", "trades", "ESH2026", 1),
            (MARCH_5, "out-of-session", "trades", "ESH2026", 1),
            (MARCH_6, "gap", "trades", None, 1),
            (MARCH_9, "clock-decreases", "trades", "ESM2026", 1),
        ],
        schema=FINDING_COLUMNS,
        orient="row",
    )
    assert_frame_equal(report.findings, expected)
    assert report.days.select("trade_date", "bar_differences").rows() == [
        (MARCH_5, None),
        (MARCH_6, 0),
        (MARCH_9, None),
    ]
    assert report.status() is QualityStatus.FLAGGED
    assert report.summary().splitlines() == [
        "Quality of synthetic ES, 2026-03-05 to 2026-03-09: flagged, 4 findings.",
        "  2026-03-05 duplicates in trades ESH2026: 1",
        "  2026-03-05 out-of-session in trades ESH2026: 1",
        "  2026-03-06 gap in trades: 1",
        "  2026-03-09 clock-decreases in trades ESM2026: 1",
    ]
    lines = report.markdown().splitlines()
    assert "| 2026-03 | 3 | 3 | 2 | 3 | 3 | 4 | 0 |" in lines
    findings = lines.index("## Findings")
    assert lines[findings + 2 : findings + 8] == [
        "| Trade date | Kind | Schema | Contract | Count |",
        "| --- | --- | --- | --- | ---: |",
        "| 2026-03-05 | duplicates | trades | ESH2026 | 1 |",
        "| 2026-03-05 | out-of-session | trades | ESH2026 | 1 |",
        "| 2026-03-06 | gap | trades |  | 1 |",
        "| 2026-03-09 | clock-decreases | trades | ESM2026 | 1 |",
    ]


def test_bars_that_differ_from_their_finer_data_are_a_finding_of_the_bars(
    tmp_path: Path, cache: Path
) -> None:
    # The 1-minute bar of ESH2026 opening at 2026-03-06 14:30 UTC closes a tick higher than its
    # trades and its 1-second bars say: a difference against each.
    store = copied_fixtures(tmp_path)
    changed = pl.col("ts_open") == utc(2026, 3, 6, 14, 30)
    higher_close = pl.when(changed).then(pl.col("close") + QUARTER_POINT).otherwise("close")
    rewrite(store, es_minutes("ESH2026"), lambda bars: bars.with_columns(close=higher_close))

    report = assess_quality(store, "synthetic", "ES", cache)

    assert report.findings.rows() == [(MARCH_6, "bar-differences", "ohlcv-1m", "ESH2026", 2)]
    assert report.days.get_column("bar_differences").to_list() == [0, 2, 0]


def test_a_price_of_zero_is_a_finding(tmp_path: Path, cache: Path) -> None:
    # The trades alone, so that nothing is rebuilt.
    shutil.copytree(SYNTHETIC / "trades", tmp_path / "synthetic" / "trades")
    store = Store(tmp_path)
    eleventh = pl.int_range(pl.len()) == 10
    zero_price = pl.when(eleventh).then(0).otherwise("price")
    rewrite(
        store, es_trades("ESH2026", MARCH_5), lambda trades: trades.with_columns(price=zero_price)
    )

    report = assess_quality(store, "synthetic", "ES", cache)

    assert report.findings.rows() == [(MARCH_5, "non-positive-prices", "trades", "ESH2026", 1)]


def test_crude_oil_below_zero_is_allowed_on_the_days_it_traded_there_only(
    tmp_path: Path, cache: Path
) -> None:
    # WTI's May 2020 contract settled at -37.63 on 2020-04-20 and expired on 04-21. CME energy
    # trades from 17:00 to 16:00 Chicago, on CDT (UTC-5) then, so 15:00 UTC is inside each
    # session. The same below-zero price on 04-22 is a finding.
    store = Store(tmp_path)
    trades = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="CL")
    store.write_dataset_metadata(trades, CONTRACT_SIZES)
    for contract, instrument_id, day in (
        ("CLK2020", 3001, date(2020, 4, 20)),
        ("CLK2020", 3001, date(2020, 4, 21)),
        ("CLM2020", 3002, date(2020, 4, 22)),
    ):
        prints = crude_trades(utc(day.year, day.month, day.day, 15), -37_630_000_000, instrument_id)
        store.write_partition(Partition(dataset=trades, contract=contract, key=day), prints)

    report = assess_quality(store, "synthetic", "CL", cache)

    assert report.findings.rows() == [
        (date(2020, 4, 22), "non-positive-prices", "trades", "CLM2020", 1)
    ]


def test_the_vendors_conditions_mark_the_trade_dates_their_days_touch(
    tmp_path: Path, cache: Path
) -> None:
    # The batch's bars of ESH2026 fall on trade dates 2026-03-05, 03-06, and 03-09, and its
    # condition.json marks the UTC day 03-06 degraded, which lies inside the session of trade
    # date 03-06: it opens on 03-05 at 23:00 UTC and lasts until the next open, on Sunday. The
    # batch holds the vendor's 1-minute bars only, so no day is rebuilt.
    store = Store(tmp_path / "data")
    import_databento(BATCH, store, cache)

    report = assess_quality(store, "databento", "ES", cache)

    assert report.days.select("trade_date", "vendor_condition").rows() == [
        (MARCH_5, "available"),
        (MARCH_6, "degraded"),
        (MARCH_9, "available"),
    ]
    assert report.vendor_days == (ConditionDay(day=MARCH_6, condition=VendorCondition.DEGRADED),)
    assert report.days.get_column("bar_differences").null_count() == report.days.height


def test_bars_after_the_end_of_the_data_are_held_back_on_its_last_trade_date(
    tmp_path: Path, cache: Path
) -> None:
    # The copy's last bar of ESH2026 closes at 2026-03-09 19:00 UTC, two hours before the close
    # at 21:00 UTC (Chicago keeps CDT from 03-08): 120 one-minute buckets are held back.
    store = Store(tmp_path)
    minutes = es_minutes("ESH2026")
    store.write_dataset_metadata(minutes.dataset, CONTRACT_SIZES)
    bars = FIXTURES.scan_partition(minutes).filter(pl.col("ts_close") <= utc(2026, 3, 9, 19))
    store.write_partition(minutes, bars.collect())

    report = assess_quality(store, "synthetic", "ES", cache)

    assert report.days.select("trade_date", "held_back_bars").rows() == [
        (MARCH_5, 0),
        (MARCH_6, 0),
        (MARCH_9, 120),
    ]
    assert report.findings.is_empty()
    assert report.markdown().splitlines()[-1] == (
        "The data ends at 2026-03-09T19:00:00Z, inside the session of 2026-03-09: its last "
        "120 one-minute buckets are held back until later data completes it."
    )


def test_the_markdown_summary_shows_the_coverage_of_each_month(
    clean_report: QualityReport,
) -> None:
    assert clean_report.markdown().splitlines() == [
        "# Quality of synthetic ES",
        "",
        "Trade dates 2026-03-05 to 2026-03-09: 3 sessions, 3 with records, 2 contracts.",
        "",
        "Status: clean, no findings.",
        "",
        "## Coverage by month",
        "",
        "| Month | Sessions | With records | Tick days | 1s days | 1m days | Findings "
        "| Vendor-flagged days |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        "| 2026-03 | 3 | 3 | 3 | 3 | 3 | 0 | 0 |",
        "",
        "## Findings",
        "",
        "None.",
        "",
        "## Days the vendor flagged",
        "",
        "The provider synthetic gives no conditions.",
        "",
        "## Prints in breaks and halts",
        "",
        "Received in the break after a close, keeping their session's trade date: 3, on "
        "2026-03-06.",
        "Received inside a halt: none.",
        "",
        "## Bars against finer data",
        "",
        "Rebuilt and compared on 3 of 3 trade dates: no differences.",
        "A trade date is compared when the store holds its bars and finer data and its records "
        "hold no finding.",
        "",
        "## Last session",
        "",
        "The data ends at 2026-03-09T21:00:00Z, with its last session, 2026-03-09, complete.",
    ]


def test_a_written_report_reads_back_with_its_status_and_last_trade_date(
    tmp_path: Path, clean_report: QualityReport
) -> None:
    reports = tmp_path / "data" / "reports"
    unchecked = quality_standing(reports, "synthetic", "ES")

    folder = write_quality_report(clean_report, reports)

    assert unchecked == QualityStanding(status=QualityStatus.UNCHECKED, checked_through=None)
    assert folder == reports / "synthetic" / "ES"
    assert sorted(path.name for path in folder.iterdir()) == [
        "days.parquet",
        "findings.parquet",
        "quality.md",
    ]
    assert_frame_equal(pl.read_parquet(folder / "days.parquet"), clean_report.days)
    assert_frame_equal(pl.read_parquet(folder / "findings.parquet"), clean_report.findings)
    assert (folder / "quality.md").read_bytes() == clean_report.markdown().encode("utf-8")
    assert quality_standing(reports, "synthetic", "ES") == QualityStanding(
        status=QualityStatus.CLEAN, checked_through=MARCH_9
    )
    assert Store(tmp_path / "data").list_datasets() == ()


def test_a_root_without_trades_or_bars_from_the_provider_is_refused(cache: Path) -> None:
    with pytest.raises(ValueError, match="Expected trades or bars of NQ from synthetic"):
        assess_quality(FIXTURES, "synthetic", "NQ", cache)
