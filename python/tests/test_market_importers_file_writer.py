from datetime import date
from pathlib import Path

import pytest
from databento_dbn import F_LAST, Action, Schema, Side, TradeMsg

from dbn_files import dbn_content, mapping, utc, write_dbn
from fefat.market.importers.canonical import RecordPlacement, active_days
from fefat.market.importers.dbn import read_dbn
from fefat.market.importers.file_writer import checked_records, write_records
from fefat.market.importers.partition_buffers import CONTRACT_SIZE
from fefat.market.importers.partition_merge import DifferingRecords
from fefat.market.instruments import STATIC_TABLE
from fefat.market.layout import DatasetMetadata, DatasetOrigin
from fefat.market.store import Store

ESH6 = [mapping("ESH6", 1001, date(2025, 3, 21), date(2026, 3, 21))]
IMPORTED = DatasetMetadata(
    size_unit=CONTRACT_SIZE,
    origin=DatasetOrigin.IMPORT,
    licence_scope="Synthetic test data; no licence applies",
)
REFUSE = DifferingRecords.REFUSE
TRADE_BYTES = 48
"""A trade record's size: a chunk this long completes at most one record, so each frame holds
one trade, as the chunks of a large file split its records."""


def trades_file(folder: Path, *instants: int) -> Path:
    trades = [
        TradeMsg(publisher_id=1, instrument_id=1001, ts_event=instant, price=6_750_000_000_000, size=1, action=Action("T"), side=Side("B"), depth=0, ts_recv=instant, flags=F_LAST, sequence=sequence)
        for sequence, instant in enumerate(instants)
    ]  # fmt: skip
    return write_dbn(folder / "es.trades.dbn", dbn_content(Schema("trades"), ESH6, trades))


def placement_of(path: Path, cache_folder: Path) -> RecordPlacement:
    metadata, frames = read_dbn(path)
    days = active_days(frames, metadata.schema_name)
    return RecordPlacement(path, metadata, days, "databento", STATIC_TABLE, cache_folder)


def test_a_record_earlier_than_the_last_of_the_previous_frame_is_counted(tmp_path: Path) -> None:
    path = trades_file(tmp_path, utc(2026, 3, 9, 14, 31), utc(2026, 3, 9, 14, 30))
    _, frames = read_dbn(path, TRADE_BYTES)

    report = checked_records(
        frames, placement_of(path, tmp_path), Store(tmp_path / "data"), "x", IMPORTED, REFUSE
    )

    assert report.clock_decreases == 1
    assert report.first_clock_decrease is not None
    assert report.first_clock_decrease.record == 1


def test_the_check_writes_nothing_and_a_second_pass_writes_the_partitions(
    tmp_path: Path,
) -> None:
    # Step 5.14: the whole file is read against the store before a byte is written, each
    # partition as it completes while the file streams, a frame a trade here.
    path = trades_file(tmp_path, utc(2026, 3, 2, 14, 30), utc(2026, 3, 12, 14, 30))
    store, placement = Store(tmp_path / "data"), placement_of(path, tmp_path)

    report = checked_records(
        read_dbn(path, TRADE_BYTES)[1], placement, store, "x", IMPORTED, REFUSE
    )
    checked_alone = not (tmp_path / "data").exists()
    write_records(read_dbn(path, TRADE_BYTES)[1], placement, store, IMPORTED, REFUSE)

    (merge,) = report.merges
    assert checked_alone
    assert (merge.records_added, merge.partitions_changed) == (2, 2)
    assert [file.partition.key for file in store.list_partitions()] == [
        date(2026, 3, 2),
        date(2026, 3, 12),
    ]


def test_a_partition_completes_while_the_file_streams_and_refuses_later_rows(
    tmp_path: Path,
) -> None:
    # Monday 2026-03-02's trades are complete once the file reaches Thursday 03-12, ten days on,
    # so a trade of 03-02 after that is out of order across partitions. The check refuses the
    # file, where the writer had already written 03-02's partition (D-98).
    path = trades_file(
        tmp_path, utc(2026, 3, 2, 14, 30), utc(2026, 3, 12, 14, 30), utc(2026, 3, 2, 14, 31)
    )
    _, frames = read_dbn(path, TRADE_BYTES)
    store = Store(tmp_path / "data")

    with pytest.raises(ValueError, match="got more after it was complete"):
        checked_records(frames, placement_of(path, tmp_path), store, "x", IMPORTED, REFUSE)

    assert not (tmp_path / "data").exists()


def test_a_day_the_symbology_does_not_cover_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    # ESH6's interval ends on 2026-03-21, so the first pass already knows that the trade of
    # 03-23 has no contract: the placement refuses the file before the second pass writes.
    path = trades_file(tmp_path, utc(2026, 3, 9, 14, 30), utc(2026, 3, 23, 14, 30))

    with pytest.raises(ValueError, match="got none for instrument_id 1001 on 2026-03-23"):
        placement_of(path, tmp_path)
