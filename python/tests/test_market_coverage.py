from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from fefat.market.coverage import DatasetCoverage, dataset_coverage
from fefat.market.layout import Dataset, Partition
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Store(ROOT / "fixtures")
MARCH_5, MARCH_9 = date(2026, 3, 5), date(2026, 3, 9)


def utc(*fields: int) -> int:
    """The instant of a UTC date and time, in nanoseconds since the Unix epoch."""
    year, month, day, *clock = fields
    return int(datetime(year, month, day, *clock, tzinfo=UTC).timestamp()) * 1_000_000_000


def es(schema: str) -> Dataset:
    return Dataset(provider="synthetic", schema_name=parse_schema_name(schema), root="ES")


def es_trades(contract: str, day: date) -> Partition:
    return Partition(dataset=es("trades"), contract=contract, key=day)


def test_a_datasets_coverage_runs_from_its_first_trade_date_to_its_last(tmp_path: Path) -> None:
    last_trades = [FIXTURES.scan_partition(es_trades(c, MARCH_9)) for c in ("ESH2026", "ESM2026")]
    last_received = pl.concat(last_trades).select(pl.col("ts_recv").max()).collect().item()

    assert dataset_coverage(FIXTURES, es("ohlcv-1m")) == DatasetCoverage(
        contracts=("ESH2026", "ESM2026"),
        first_trade_date=MARCH_5,
        last_trade_date=MARCH_9,
        received_until=utc(2026, 3, 9, 21),
    )
    assert dataset_coverage(FIXTURES, es("trades")) == DatasetCoverage(
        contracts=("ESH2026", "ESM2026"),
        first_trade_date=MARCH_5,
        last_trade_date=MARCH_9,
        received_until=last_received + 1,
    )
    assert dataset_coverage(Store(tmp_path), es("trades")) is None


def test_a_dataset_whose_records_fall_in_no_session_is_refused() -> None:
    statistics = Dataset(
        provider="synthetic", schema_name=parse_schema_name("statistics"), root="ES"
    )

    with pytest.raises(ValueError, match="Expected a dataset of trades, TBBO, or bars"):
        dataset_coverage(FIXTURES, statistics)
