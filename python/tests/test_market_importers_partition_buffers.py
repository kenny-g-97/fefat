from datetime import date
from decimal import Decimal
from pathlib import Path

import polars as pl
import pytest

from dbn_files import NANOSECONDS_PER_MINUTE, utc
from fefat.market.importers.partition_buffers import CONTRACT_SIZE, PartitionBuffers
from fefat.market.layout import (
    Dataset,
    DatasetMetadata,
    DatasetOrigin,
    Partition,
    SizeUnit,
    YearMonth,
)
from fefat.market.schema import parse_schema_name, polars_schema
from fefat.market.store import Store

MINUTE_BARS = parse_schema_name("ohlcv-1m")
IMPORTED = DatasetMetadata(
    size_unit=CONTRACT_SIZE,
    origin=DatasetOrigin.IMPORT,
    licence_scope="Synthetic test data; no licence applies",
)
MARCH = Partition(
    dataset=Dataset(provider="databento", schema_name=MINUTE_BARS, root="ES"),
    contract="ESH2026",
    key=YearMonth(year=2026, month=3),
)


def march_bars(*opens: int) -> pl.DataFrame:
    """One-minute bars of Monday 2026-03-30's session opening at `opens`, a volume each."""
    return pl.DataFrame(
        {
            "ts_open": list(opens),
            "ts_close": [ts_open + NANOSECONDS_PER_MINUTE for ts_open in opens],
            "trade_date": [date(2026, 3, 30)] * len(opens),
            "instrument_id": [1001] * len(opens),
            "open": [1] * len(opens),
            "high": [2] * len(opens),
            "low": [0] * len(opens),
            "close": [1] * len(opens),
            "volume": list(range(1, len(opens) + 1)),
            "trade_count": [None] * len(opens),
            "vwap": [None] * len(opens),
        },
        schema=polars_schema(MINUTE_BARS),
    )


def in_march(rows: pl.DataFrame) -> dict[Partition, pl.DataFrame]:
    return dict([(MARCH, rows)])


MONDAY_BARS = march_bars(utc(2026, 3, 30, 14, 30), utc(2026, 3, 30, 14, 31))


def test_a_partition_is_written_once_the_clock_is_more_than_a_week_past_its_last_day(
    tmp_path: Path,
) -> None:
    # March's last trade date is the 31st: a week later, 2026-04-07, a record could still be
    # out of place by a weekend and a holiday; from 2026-04-08 none can belong to March.
    store = Store(tmp_path)
    buffers = PartitionBuffers(store, "ts_open", IMPORTED)
    buffers.add(in_march(MONDAY_BARS))

    buffers.write_complete(utc(2026, 4, 7, 23, 59))
    assert not store.has_partition(MARCH)
    buffers.write_complete(utc(2026, 4, 8))

    assert store.has_partition(MARCH)
    assert (buffers.written, buffers.kept) == (1, 0)
    assert store.scan_partition(MARCH).collect().equals(MONDAY_BARS)


def test_rows_for_a_partition_already_written_are_refused(tmp_path: Path) -> None:
    buffers = PartitionBuffers(Store(tmp_path), "ts_open", IMPORTED)
    buffers.add(in_march(MONDAY_BARS))
    buffers.write_all()

    with pytest.raises(ValueError, match="got more after it was complete and written"):
        buffers.add(in_march(march_bars(utc(2026, 3, 30, 14, 32))))


def test_rows_are_written_in_the_order_of_their_clock(tmp_path: Path) -> None:
    store = Store(tmp_path)
    buffers = PartitionBuffers(store, "ts_open", IMPORTED)
    buffers.add(in_march(march_bars(utc(2026, 3, 30, 14, 31))))
    buffers.add(in_march(march_bars(utc(2026, 3, 30, 14, 30))))

    buffers.write_all()

    stored = store.scan_partition(MARCH).collect()
    assert stored.get_column("ts_open").to_list() == [
        utc(2026, 3, 30, 14, 30),
        utc(2026, 3, 30, 14, 31),
    ]


def test_a_partition_stored_with_these_rows_is_left_alone_and_one_with_others_refused(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    first = PartitionBuffers(store, "ts_open", IMPORTED)
    first.add(in_march(MONDAY_BARS))
    first.write_all()
    written = (tmp_path / MARCH.relative_path()).stat().st_mtime_ns

    again = PartitionBuffers(store, "ts_open", IMPORTED)
    again.add(in_march(MONDAY_BARS))
    again.write_all()
    overlapping = PartitionBuffers(store, "ts_open", IMPORTED)
    overlapping.add(in_march(MONDAY_BARS.head(1)))

    assert (again.written, again.kept) == (0, 1)
    assert (tmp_path / MARCH.relative_path()).stat().st_mtime_ns == written
    with pytest.raises(ValueError, match="got 2 other rows: a file that overlaps"):
        overlapping.write_all()


APRIL = Partition(dataset=MARCH.dataset, contract="ESH2026", key=YearMonth(year=2026, month=4))
APRIL_BARS = march_bars(utc(2026, 4, 1, 14, 30)).with_columns(trade_date=pl.lit(date(2026, 4, 1)))


def test_a_later_import_keeps_the_dataset_json_its_first_import_wrote(tmp_path: Path) -> None:
    # A snapshot pins dataset.json by its bytes (D-11), so rewording a source's licence scope
    # in the guide must leave the file of a dataset already imported as it was.
    store = Store(tmp_path)
    first = PartitionBuffers(store, "ts_open", IMPORTED)
    first.add(in_march(MONDAY_BARS))
    first.write_all()
    pinned = (tmp_path / MARCH.dataset.metadata_path()).read_bytes()
    reworded = IMPORTED.model_copy(update={"licence_scope": "Reworded terms of the source"})

    later = PartitionBuffers(store, "ts_open", reworded)
    later.add(dict([(APRIL, APRIL_BARS)]))
    later.write_all()

    assert store.has_partition(APRIL)
    assert (tmp_path / MARCH.dataset.metadata_path()).read_bytes() == pinned


def test_an_import_counting_sizes_in_another_unit_than_its_dataset_is_refused(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path)
    first = PartitionBuffers(store, "ts_open", IMPORTED)
    first.add(in_march(MONDAY_BARS))
    first.write_all()
    tenths = IMPORTED.model_copy(
        update={"size_unit": SizeUnit(lot=Decimal("0.1"), asset="contract")}
    )

    later = PartitionBuffers(store, "ts_open", tenths)
    later.add(dict([(APRIL, APRIL_BARS)]))

    with pytest.raises(
        ValueError,
        match=r"Expected the size unit of databento/ohlcv-1m/root=ES, 1 contract, got 0.1 "
        "contract from this import",
    ):
        later.write_all()
    assert not store.has_partition(APRIL)


def test_a_file_whose_later_partition_is_refused_writes_none_of_its_earlier_ones(
    tmp_path: Path,
) -> None:
    # The stored copies are compared before anything is written, so a refused file changes
    # nothing: a store holding half a file, with no record of it, could not be put right.
    store = Store(tmp_path)
    first = PartitionBuffers(store, "ts_open", IMPORTED)
    first.add(in_march(MONDAY_BARS))
    first.write_all()
    overlapping = PartitionBuffers(store, "ts_open", IMPORTED)
    overlapping.add(dict([(APRIL, APRIL_BARS)]))
    overlapping.add(in_march(MONDAY_BARS.head(1)))

    with pytest.raises(ValueError, match="a file that overlaps"):
        overlapping.write_all()

    assert not (tmp_path / APRIL.relative_path()).exists()
