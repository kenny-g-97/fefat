from datetime import date
from pathlib import Path

import polars as pl
import pytest

from dbn_files import NANOSECONDS_PER_MINUTE, utc
from fefat.market.importers.partition_buffers import PartitionBuffers
from fefat.market.layout import Dataset, Partition, YearMonth
from fefat.market.schema import parse_schema_name, polars_schema
from fefat.market.store import Store

MINUTE_BARS = parse_schema_name("ohlcv-1m")
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
    buffers = PartitionBuffers(store, "ts_open")
    buffers.add(in_march(MONDAY_BARS))

    buffers.write_complete(utc(2026, 4, 7, 23, 59))
    assert not store.has_partition(MARCH)
    buffers.write_complete(utc(2026, 4, 8))

    assert store.has_partition(MARCH)
    assert (buffers.written, buffers.kept) == (1, 0)
    assert store.scan_partition(MARCH).collect().equals(MONDAY_BARS)


def test_rows_for_a_partition_already_written_are_refused(tmp_path: Path) -> None:
    buffers = PartitionBuffers(Store(tmp_path), "ts_open")
    buffers.add(in_march(MONDAY_BARS))
    buffers.write_all()

    with pytest.raises(ValueError, match="got more after it was complete and written"):
        buffers.add(in_march(march_bars(utc(2026, 3, 30, 14, 32))))


def test_rows_are_written_in_the_order_of_their_clock(tmp_path: Path) -> None:
    store = Store(tmp_path)
    buffers = PartitionBuffers(store, "ts_open")
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
    first = PartitionBuffers(store, "ts_open")
    first.add(in_march(MONDAY_BARS))
    first.write_all()
    written = (tmp_path / MARCH.relative_path()).stat().st_mtime_ns

    again = PartitionBuffers(store, "ts_open")
    again.add(in_march(MONDAY_BARS))
    again.write_all()
    overlapping = PartitionBuffers(store, "ts_open")
    overlapping.add(in_march(MONDAY_BARS.head(1)))

    assert (again.written, again.kept) == (0, 1)
    assert (tmp_path / MARCH.relative_path()).stat().st_mtime_ns == written
    with pytest.raises(ValueError, match="got 2 other rows: a file that overlaps"):
        overlapping.write_all()
