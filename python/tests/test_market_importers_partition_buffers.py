from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import cast

import polars as pl
import pytest

from dbn_files import NANOSECONDS_PER_MINUTE, utc
from fefat.market.importers.partition_buffers import (
    CONTRACT_SIZE,
    MergeTally,
    PartitionBuffers,
    require_none_differing,
    write_merges,
)
from fefat.market.importers.partition_merge import DifferingRecords, RecordIdentity
from fefat.market.importers.report import DatasetMerge, DayRecords
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
BY_OPEN = RecordIdentity(clock="ts_open")
REFUSE, TAKE_THE_FILE = DifferingRecords.REFUSE, DifferingRecords.TAKE_THE_FILE
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


def march_bars(*opens: int, close: int = 1) -> pl.DataFrame:
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
            "close": [close] * len(opens),
            "volume": list(range(1, len(opens) + 1)),
            "trade_count": [None] * len(opens),
            "vwap": [None] * len(opens),
        },
        schema=polars_schema(MINUTE_BARS),
    )


def in_march(rows: pl.DataFrame) -> dict[Partition, pl.DataFrame]:
    return dict([(MARCH, rows)])


def imported(
    store: Store,
    rows: dict[Partition, pl.DataFrame],
    metadata: DatasetMetadata = IMPORTED,
    differing: DifferingRecords = REFUSE,
) -> None:
    """The rows written as an import writes them: every partition merged with what the store
    holds of it, and those that change written."""
    buffers = PartitionBuffers(store, BY_OPEN, metadata)
    buffers.add(rows)
    write_merges(store, buffers.rest(), metadata, differing)


MONDAY_BARS = march_bars(utc(2026, 3, 30, 14, 30), utc(2026, 3, 30, 14, 31))
THREE_BARS = march_bars(
    utc(2026, 3, 30, 14, 30), utc(2026, 3, 30, 14, 31), utc(2026, 3, 30, 14, 32)
)


def test_a_partition_is_complete_once_the_clock_is_more_than_a_week_past_its_last_day(
    tmp_path: Path,
) -> None:
    # March's last trade date is the 31st: a week later, 2026-04-07, a record could still be
    # out of place by a weekend and a holiday; from 2026-04-08 none can belong to March.
    store = Store(tmp_path)
    buffers = PartitionBuffers(store, BY_OPEN, IMPORTED)
    buffers.add(in_march(MONDAY_BARS))

    waiting = list(buffers.complete(utc(2026, 4, 7, 23, 59)))
    (merge,) = buffers.complete(utc(2026, 4, 8))

    assert waiting == []
    assert merge.partition == MARCH
    assert merge.rows(REFUSE).equals(MONDAY_BARS)
    assert list(buffers.rest()) == []


def test_the_buffers_write_nothing_and_the_merges_that_change_a_partition_are_written(
    tmp_path: Path,
) -> None:
    # Step 5.14: a file is gone over once to check and count, and the store stays as it was
    # until a second pass writes its merges.
    store = Store(tmp_path)
    buffers = PartitionBuffers(store, BY_OPEN, IMPORTED)
    buffers.add(in_march(MONDAY_BARS))

    merges = list(buffers.rest())
    untouched = not tmp_path.exists() or not any(tmp_path.iterdir())
    write_merges(store, merges, IMPORTED, REFUSE)

    assert untouched
    assert store.scan_partition(MARCH).collect().equals(MONDAY_BARS)
    assert store.dataset_metadata(MARCH.dataset) == IMPORTED


def test_rows_for_a_partition_already_complete_are_refused(tmp_path: Path) -> None:
    buffers = PartitionBuffers(Store(tmp_path), BY_OPEN, IMPORTED)
    buffers.add(in_march(MONDAY_BARS))
    list(buffers.rest())

    with pytest.raises(ValueError, match="got more after it was complete"):
        buffers.add(in_march(march_bars(utc(2026, 3, 30, 14, 32))))


def test_rows_are_merged_in_the_order_of_their_clock(tmp_path: Path) -> None:
    buffers = PartitionBuffers(Store(tmp_path), BY_OPEN, IMPORTED)
    buffers.add(in_march(march_bars(utc(2026, 3, 30, 14, 31))))
    buffers.add(in_march(march_bars(utc(2026, 3, 30, 14, 30))))

    (merge,) = buffers.rest()

    assert merge.rows(REFUSE).get_column("ts_open").to_list() == [
        utc(2026, 3, 30, 14, 30),
        utc(2026, 3, 30, 14, 31),
    ]


def test_a_partition_stored_with_these_rows_is_left_alone(tmp_path: Path) -> None:
    # A merge run a second time writes nothing: the partition keeps its bytes and its time,
    # and so its digest, its pins, and the caches built from it.
    store = Store(tmp_path)
    imported(store, in_march(MONDAY_BARS))
    written = (tmp_path / MARCH.relative_path()).stat().st_mtime_ns

    imported(store, in_march(MONDAY_BARS))
    imported(store, in_march(MONDAY_BARS.head(1)))

    assert (tmp_path / MARCH.relative_path()).stat().st_mtime_ns == written
    assert store.scan_partition(MARCH).collect().equals(MONDAY_BARS)


def test_a_partition_the_store_holds_part_of_gains_the_rest(tmp_path: Path) -> None:
    # Step 5.14, where the store refused such a file: a file that overlaps an imported one is
    # merged into it, the records the store lacks added in clock order.
    store = Store(tmp_path)
    imported(store, in_march(THREE_BARS.tail(2)))

    imported(store, in_march(THREE_BARS.head(2)))

    assert store.scan_partition(MARCH).collect().equals(THREE_BARS)


APRIL = Partition(dataset=MARCH.dataset, contract="ESH2026", key=YearMonth(year=2026, month=4))
APRIL_BARS = march_bars(utc(2026, 4, 1, 14, 30)).with_columns(trade_date=pl.lit(date(2026, 4, 1)))


def test_a_later_import_keeps_the_dataset_json_its_first_import_wrote(tmp_path: Path) -> None:
    # A snapshot pins dataset.json by its bytes (D-11), so rewording a source's licence scope
    # in the guide must leave the file of a dataset already imported as it was.
    store = Store(tmp_path)
    imported(store, in_march(MONDAY_BARS))
    pinned = (tmp_path / MARCH.dataset.metadata_path()).read_bytes()
    reworded = IMPORTED.model_copy(update={"licence_scope": "Reworded terms of the source"})

    imported(store, dict([(APRIL, APRIL_BARS)]), reworded)

    assert store.has_partition(APRIL)
    assert (tmp_path / MARCH.dataset.metadata_path()).read_bytes() == pinned


@pytest.mark.parametrize(
    "rows",
    [dict([(APRIL, APRIL_BARS)]), in_march(MONDAY_BARS), in_march(THREE_BARS)],
    ids=["a new partition", "records the store holds", "a stored partition's new records"],
)
def test_an_import_counting_sizes_in_another_unit_than_its_dataset_is_refused(
    tmp_path: Path, rows: dict[Partition, pl.DataFrame]
) -> None:
    # The unit is checked for every dataset a file reaches, as its partitions are read against
    # the store, whether or not the file adds a record (the design review of step 5.14).
    store = Store(tmp_path)
    imported(store, in_march(MONDAY_BARS))
    tenths = IMPORTED.model_copy(
        update={"size_unit": SizeUnit(lot=Decimal("0.1"), asset="contract")}
    )
    later = PartitionBuffers(store, BY_OPEN, tenths)
    later.add(rows)

    with pytest.raises(
        ValueError,
        match=r"Expected the size unit of databento/ohlcv-1m/root=ES, 1 contract, got 0.1 "
        "contract from this import",
    ):
        list(later.rest())
    assert not store.has_partition(APRIL)
    assert store.scan_partition(MARCH).collect().equals(MONDAY_BARS)


def tallied(
    store: Store, rows: dict[Partition, pl.DataFrame], on_differing: DifferingRecords
) -> tuple[DatasetMerge, ...]:
    """What the rows add to each dataset, as an import's check counts it, nothing written."""
    buffers = PartitionBuffers(store, BY_OPEN, IMPORTED)
    buffers.add(rows)
    tally = MergeTally(on_differing)
    for merge in buffers.rest():
        tally.add(merge)
    return tally.datasets()


def test_a_file_whose_later_partition_differs_is_refused_before_any_is_written(
    tmp_path: Path,
) -> None:
    # Every partition is read against the store before anything is written, so a refused file
    # changes nothing: a store holding half a file, with no record of it, could not be put right.
    store = Store(tmp_path)
    imported(store, in_march(MONDAY_BARS))
    changed = march_bars(utc(2026, 3, 30, 14, 31), close=7)
    merges = tallied(store, dict([(APRIL, APRIL_BARS), (MARCH, changed)]), REFUSE)

    with pytest.raises(
        ValueError,
        match="got 1 with other values in databento/ohlcv-1m/root=ES, the first on trade date "
        "2026-03-30: nothing was written",
    ):
        require_none_differing(merges, Path("later.dbn"))

    assert not (tmp_path / APRIL.relative_path()).exists()
    assert store.scan_partition(MARCH).collect().equals(MONDAY_BARS)


def test_a_write_stops_at_records_that_differ_which_its_check_would_have_refused(
    tmp_path: Path,
) -> None:
    # The engine accuracy review of step 5.14: a write under refuse left the differing records
    # out and wrote the rest, so a store or a file changed between an import's check and its
    # write ended as a file recorded whole. Here no check comes before the write.
    store = Store(tmp_path)
    imported(store, in_march(MONDAY_BARS))
    changed = march_bars(utc(2026, 3, 30, 14, 31), utc(2026, 3, 30, 14, 32), close=7)

    with pytest.raises(
        ValueError,
        match="got 1 of the file's records with other values than the stored ones, after 0 of "
        "the file's partitions were written: the store or the file changed while the import ran",
    ):
        imported(store, in_march(changed))

    assert store.scan_partition(MARCH).collect().equals(MONDAY_BARS)


def test_a_write_given_the_options_text_stops_at_records_that_differ(tmp_path: Path) -> None:
    # The importers read the option's text at their entries. A text that reaches the write is
    # not the option, so the write stops at records that differ, where it would have left them
    # out and written the rest of the file (the code review of the fixes).
    store = Store(tmp_path)
    imported(store, in_march(MONDAY_BARS))
    changed = march_bars(utc(2026, 3, 30, 14, 31), utc(2026, 3, 30, 14, 32), close=7)

    with pytest.raises(ValueError, match="changed while the import ran"):
        imported(store, in_march(changed), differing=cast(DifferingRecords, "take-file"))

    assert store.scan_partition(MARCH).collect().equals(MONDAY_BARS)


def test_the_files_records_stand_where_the_import_takes_them(tmp_path: Path) -> None:
    store = Store(tmp_path)
    imported(store, in_march(MONDAY_BARS))
    changed = march_bars(utc(2026, 3, 30, 14, 31), close=7)

    (merge,) = tallied(store, in_march(changed), TAKE_THE_FILE)
    require_none_differing([merge], Path("later.dbn"))
    imported(store, in_march(changed), differing=TAKE_THE_FILE)

    assert (merge.records_differing, merge.stored_records_disputed) == (1, 1)
    assert merge.replaces() and not merge.refuses()
    assert (merge.partitions_changed, merge.partitions_unchanged) == (1, 0)
    assert store.scan_partition(MARCH).collect().get_column("close").to_list() == [1, 7]


def test_the_tally_tells_new_sessions_from_those_the_store_holds(tmp_path: Path) -> None:
    # Done means 3: per dataset, the sessions the file adds, apart from the stored sessions it
    # adds records to, the records the store already holds, and those that differ.
    store = Store(tmp_path)
    imported(store, in_march(MONDAY_BARS))
    tuesday = march_bars(utc(2026, 3, 31, 14, 30), utc(2026, 3, 31, 14, 31)).with_columns(
        trade_date=pl.lit(date(2026, 3, 31))
    )
    rows = dict([(MARCH, pl.concat([THREE_BARS, tuesday])), (APRIL, APRIL_BARS)])

    (merge,) = tallied(store, rows, REFUSE)

    assert merge.dataset == MARCH.dataset
    assert (merge.records_added, merge.records_held, merge.records_differing) == (4, 2, 0)
    assert merge.new_sessions == (
        DayRecords(trade_date=date(2026, 3, 31), records=2),
        DayRecords(trade_date=date(2026, 4, 1), records=1),
    )
    assert merge.extended_sessions == (DayRecords(trade_date=date(2026, 3, 30), records=1),)
    assert merge.differing_sessions == ()
    assert (merge.partitions_changed, merge.partitions_unchanged) == (2, 0)
    assert merge.lines() == [
        "  databento/ohlcv-1m/root=ES:",
        "    New sessions: 3 records on 2 trade dates: 2026-03-31 (2), 2026-04-01 (1)",
        "    Sessions the store holds that gain records: 1 record on 1 trade date: 2026-03-30 (1)",
        "    Records: 4 new, 2 already held, 0 that differ",
        "    Partitions: 2 that change, 0 unchanged",
    ]


def test_a_session_is_new_to_the_contract_that_lacked_it(tmp_path: Path) -> None:
    # The code review of step 5.14: the store holds Monday of ESH2026 alone. A file with one
    # more bar of it, and with ESM2026's bars of that Monday, brings ESM2026 a new session, which
    # read as a stored session gaining records while a session was held or new for its dataset.
    store = Store(tmp_path)
    imported(store, in_march(MONDAY_BARS))
    next_contract = Partition(dataset=MARCH.dataset, contract="ESM2026", key=MARCH.key)

    (merge,) = tallied(store, dict([(MARCH, THREE_BARS), (next_contract, MONDAY_BARS)]), REFUSE)

    monday = date(2026, 3, 30)
    assert merge.new_sessions == (DayRecords(trade_date=monday, records=2),)
    assert merge.extended_sessions == (DayRecords(trade_date=monday, records=1),)
    assert (merge.records_added, merge.records_held) == (3, 2)
