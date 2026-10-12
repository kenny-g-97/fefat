from datetime import date
from pathlib import PurePosixPath

import pytest

from fefat.market.layout import Dataset, Partition, Partitioning, YearMonth, partitioning
from fefat.market.schema import parse_schema_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("trades", Partitioning.TRADE_DATE),
        ("tbbo", Partitioning.TRADE_DATE),
        ("ohlcv-1s", Partitioning.TRADE_DATE),
        ("ohlcv-10s", Partitioning.TRADE_DATE),
        ("ohlcv-1m", Partitioning.MONTH),
        ("ohlcv-5m", Partitioning.CONTRACT),
        ("ohlcv-1h", Partitioning.CONTRACT),
        ("ohlcv-1d", Partitioning.CONTRACT),
        ("definitions", Partitioning.CONTRACT),
        ("statistics", Partitioning.CONTRACT),
        ("funding", Partitioning.CONTRACT),
    ],
)
def test_ticks_and_seconds_go_per_trade_date_minutes_per_month_and_the_rest_per_contract(
    name: str, expected: Partitioning
) -> None:
    assert partitioning(parse_schema_name(name)) is expected


@pytest.mark.parametrize(
    ("path", "key"),
    [
        ("synthetic/trades/root=ES/contract=ESH6/date=2026-03-05/part.parquet", date(2026, 3, 5)),
        (
            "synthetic/ohlcv-1m/root=ES/contract=ESH6/month=2026-03/part.parquet",
            YearMonth(year=2026, month=3),
        ),
        ("vendor/statistics/root=MES/contract=MESZ6/part.parquet", None),
    ],
)
def test_a_partition_and_its_path_convert_both_ways(
    path: str, key: date | YearMonth | None
) -> None:
    partition = Partition.from_relative_path(PurePosixPath(path))

    assert partition.key == key
    assert partition.relative_path() == PurePosixPath(path)


@pytest.mark.parametrize(
    "path",
    [
        "synthetic/trades/root=ES/contract=ESH6/part.parquet",
        "synthetic/ohlcv-1m/root=ES/contract=ESH6/date=2026-03-05/part.parquet",
        "synthetic/statistics/root=ES/contract=ESH6/month=2026-03/part.parquet",
        "synthetic/trades/ES/contract=ESH6/date=2026-03-05/part.parquet",
        "synthetic/trades/root=ES/ESH6/date=2026-03-05/part.parquet",
        "synthetic/trades/root=ES/contract=ESH6/date=20260305/part.parquet",
        "synthetic/ohlcv-1m/root=ES/contract=ESH6/month=2026-3/part.parquet",
        "synthetic/trades/root=ES/contract=ESH6/week=10/part.parquet",
        "synthetic/trades/root=ES/contract=ESH6/date=2026-03-05/data.parquet",
        "synthetic/trades/root=E S/contract=ESH6/date=2026-03-05/part.parquet",
        "synthetic/trades/root=ES/contract=ESH6./date=2026-03-05/part.parquet",
        "synthetic/candles/root=ES/contract=ESH6/part.parquet",
        "raw/trades/root=ES/contract=ESH6/date=2026-03-05/part.parquet",
        "trades/root=ES/contract=ESH6/date=2026-03-05/part.parquet",
    ],
)
def test_a_path_outside_the_layout_is_refused(path: str) -> None:
    with pytest.raises(ValueError, match="Expected a partition path"):
        Partition.from_relative_path(PurePosixPath(path))


@pytest.mark.parametrize("provider", ["raw", "RAW", "Raw"])
def test_raw_is_kept_for_the_vendors_original_files(provider: str) -> None:
    with pytest.raises(ValueError, match="the folder of the vendors' raw files"):
        Dataset(provider=provider, schema_name=parse_schema_name("trades"), root="ES")


def test_a_month_reads_back_as_written_and_a_malformed_one_is_refused() -> None:
    assert str(YearMonth.parse("2026-03")) == "2026-03"
    for malformed in ["2026-13", "2026-3", "26-03", "2026-03-01"]:
        with pytest.raises(ValueError):
            YearMonth.parse(malformed)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2026, 2, 15), date(2026, 3, 1), True),
        (date(2026, 3, 31), date(2026, 4, 2), True),
        (date(2026, 1, 1), date(2026, 12, 31), True),
        (date(2026, 2, 1), date(2026, 2, 28), False),
        (date(2026, 4, 1), date(2026, 4, 30), False),
    ],
)
def test_a_month_overlaps_a_range_of_days_that_touches_it(
    start: date, end: date, expected: bool
) -> None:
    assert YearMonth(year=2026, month=3).overlaps(start, end) is expected
