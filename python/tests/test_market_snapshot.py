import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path, PurePosixPath

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fefat.market.layout import (
    Dataset,
    DatasetMetadata,
    DatasetOrigin,
    Partition,
    PartitionRequest,
    SizeUnit,
)
from fefat.market.schema import parse_schema_name
from fefat.market.snapshot import FileDigest, Snapshot
from fefat.market.store import Store
from fefat.market.store_files import DIGEST_SUFFIX, FileDigestRecord

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
FIXTURE_STORE = Store(FIXTURES)
FIXTURE_ENTRIES = {
    f"synthetic/{entry['path']}": entry
    for entry in json.loads((FIXTURES / "synthetic" / "MANIFEST.json").read_text("utf-8"))["files"]
}
ES_TRADES = PartitionRequest(
    dataset=Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES"),
    start=date(2026, 3, 5),
    end=date(2026, 3, 9),
)
NO_LICENCE = "Synthetic test data; no licence applies"
ES_SIZE = DatasetMetadata(
    size_unit=SizeUnit(lot=Decimal(1), asset="contract"),
    origin=DatasetOrigin.IMPORT,
    licence_scope=NO_LICENCE,
)
TRADES_OF_MARCH_5 = Partition.from_relative_path(
    PurePosixPath("synthetic/trades/root=ES/contract=ESH2026/date=2026-03-05/part.parquet")
)
TRADES_OF_MARCH_6 = Partition.from_relative_path(
    PurePosixPath("synthetic/trades/root=ES/contract=ESH2026/date=2026-03-06/part.parquet")
)
SNAPSHOT_PROGRAM = """
import sys
from pathlib import Path

from fefat.market.layout import PartitionRequest
from fefat.market.store import Store

request = PartitionRequest.model_validate_json(sys.argv[2])
sys.stdout.write(Store(Path(sys.argv[1])).snapshot(request).model_dump_json())
"""
UNKNOWN_SHA256 = "0" * 64
# Each fixture session's close and the open of the session after it. A print received in the
# break between them keeps the session's trade date, as the vendor's do: the fixtures plant one
# 400 ms after the close of ES's 2026-03-06 (step 1.5).
SESSION_ENDS = {
    "ES": {
        date(2026, 3, 5): (
            datetime(2026, 3, 5, 22, tzinfo=UTC),
            datetime(2026, 3, 5, 23, tzinfo=UTC),
        ),
        date(2026, 3, 6): (
            datetime(2026, 3, 6, 22, tzinfo=UTC),
            datetime(2026, 3, 8, 22, tzinfo=UTC),
        ),
        date(2026, 3, 9): (
            datetime(2026, 3, 9, 21, tzinfo=UTC),
            datetime(2026, 3, 9, 22, tzinfo=UTC),
        ),
    },
    "BTCUSDT-PERP": {
        date(2026, 3, 7): (datetime(2026, 3, 8, tzinfo=UTC), datetime(2026, 3, 8, tzinfo=UTC))
    },
}
SESSION_WITH_A_PRINT_IN_THE_BREAK = ("ES", date(2026, 3, 6))


def store_with_the_es_trades(folder: Path) -> Store:
    store = Store(folder)
    store.write_dataset_metadata(ES_TRADES.dataset, ES_SIZE)
    for partition in (TRADES_OF_MARCH_5, TRADES_OF_MARCH_6):
        store.write_partition(partition, FIXTURE_STORE.scan_partition(partition).collect())
    return store


def snapshot_in_a_new_process(folder: Path, request: PartitionRequest, hash_seed: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", SNAPSHOT_PROGRAM, str(folder), request.model_dump_json()],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": hash_seed},
    )
    return completed.stdout


def test_a_snapshot_is_byte_identical_across_two_runs_and_changes_with_one_partitions_bytes(
    tmp_path: Path,
) -> None:
    store = store_with_the_es_trades(tmp_path)
    first = snapshot_in_a_new_process(tmp_path, ES_TRADES, hash_seed="1")
    second = snapshot_in_a_new_process(tmp_path, ES_TRADES, hash_seed="2")
    shorter = store.scan_partition(TRADES_OF_MARCH_6).collect().head(-1)
    store.write_partition(TRADES_OF_MARCH_6, shorter)
    before = Snapshot.model_validate_json(first)
    after = store.snapshot(ES_TRADES)

    assert second == first
    assert len(before.partitions) == 2
    assert after.sha256 != before.sha256
    assert [digest.path for digest in after.partitions if digest not in before.partitions] == [
        TRADES_OF_MARCH_6.relative_path().as_posix()
    ]


def test_a_snapshot_changes_when_the_size_unit_of_its_dataset_changes(tmp_path: Path) -> None:
    store = store_with_the_es_trades(tmp_path)
    before = store.snapshot(ES_TRADES)
    mini_lots = DatasetMetadata(
        size_unit=SizeUnit(lot=Decimal("0.1"), asset="contract"),
        origin=DatasetOrigin.IMPORT,
        licence_scope=NO_LICENCE,
    )

    store.write_dataset_metadata(ES_TRADES.dataset, mini_lots)

    assert store.snapshot(ES_TRADES).sha256 != before.sha256


def test_a_snapshot_among_a_listing_taken_before_is_the_one_the_store_gives(
    tmp_path: Path,
) -> None:
    # Step 3.3: the feature cache lists a dataset once and takes many snapshots among it.
    store = store_with_the_es_trades(tmp_path)
    listing = store.list_partitions(ES_TRADES.dataset)
    march_6 = date(2026, 3, 6)
    one_day = PartitionRequest(dataset=ES_TRADES.dataset, start=march_6, end=march_6)

    assert store.snapshot(ES_TRADES, among=listing) == store.snapshot(ES_TRADES)
    assert store.snapshot(one_day, among=listing) == store.snapshot(one_day)
    assert len(store.snapshot(one_day, among=listing).partitions) == 1


def test_a_snapshot_pins_each_files_sha256_and_hashes_its_request_with_their_listing() -> None:
    snapshot = FIXTURE_STORE.snapshot(ES_TRADES)
    files = sorted((snapshot.metadata, *snapshot.partitions), key=lambda file: file.path)
    request_line = "request synthetic/trades/root=ES 2026-03-05 2026-03-09\n"
    listing = "".join(f"{file.sha256}  {file.path}\n" for file in files)

    assert {file.path: (file.size_bytes, file.sha256) for file in files} == {
        path: (entry["bytes"], entry["sha256"])
        for path, entry in FIXTURE_ENTRIES.items()
        if path.startswith("synthetic/trades/root=ES/")
    }
    assert snapshot.metadata.path == "synthetic/trades/root=ES/dataset.json"
    assert snapshot.sha256 == hashlib.sha256((request_line + listing).encode()).hexdigest()


def test_two_ranges_that_read_the_same_files_get_different_snapshots() -> None:
    minute_bars = Dataset(
        provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES"
    )
    narrow = PartitionRequest(dataset=minute_bars, start=date(2026, 3, 5), end=date(2026, 3, 6))
    wide = PartitionRequest(dataset=minute_bars, start=date(2026, 3, 5), end=date(2026, 3, 9))

    narrow_snapshot, wide_snapshot = FIXTURE_STORE.snapshot(narrow), FIXTURE_STORE.snapshot(wide)

    assert narrow_snapshot.partitions == wide_snapshot.partitions
    assert narrow_snapshot.sha256 != wide_snapshot.sha256


def test_a_snapshot_whose_hash_does_not_cover_its_files_is_refused() -> None:
    snapshot = FIXTURE_STORE.snapshot(ES_TRADES)

    with pytest.raises(ValueError, match="Expected the snapshot hash"):
        Snapshot(
            request=snapshot.request,
            metadata=snapshot.metadata,
            partitions=snapshot.partitions[:-1],
            sha256=snapshot.sha256,
        )


@pytest.mark.parametrize(
    "path",
    [
        "../../outside.parquet",
        "synthetic/trades/root=BTCUSDT-PERP/contract=BTCUSDT-PERP/date=2026-03-07/part.parquet",
        "synthetic/trades/root=ES/contract=ESH2026/date=2026-03-10/part.parquet",
    ],
)
def test_a_snapshot_read_back_with_a_partition_its_request_does_not_select_is_refused(
    path: str,
) -> None:
    snapshot = FIXTURE_STORE.snapshot(ES_TRADES)
    stranger = FileDigest(path=path, size_bytes=1, sha256=UNKNOWN_SHA256)

    with pytest.raises(ValueError, match="Expected"):
        Snapshot.of(ES_TRADES, snapshot.metadata, (stranger,))


def test_a_snapshot_read_back_with_another_datasets_metadata_is_refused() -> None:
    snapshot = FIXTURE_STORE.snapshot(ES_TRADES)
    btc_metadata = FileDigest(
        path="synthetic/trades/root=BTCUSDT-PERP/dataset.json", size_bytes=1, sha256=UNKNOWN_SHA256
    )

    with pytest.raises(ValueError, match="Expected the metadata"):
        Snapshot.of(ES_TRADES, btc_metadata, snapshot.partitions)


def test_reading_a_snapshot_returns_the_rows_its_request_scans() -> None:
    snapshot = FIXTURE_STORE.snapshot(ES_TRADES)

    read = FIXTURE_STORE.read(snapshot).sort("ts_recv", "sequence")
    scanned = FIXTURE_STORE.scan(ES_TRADES).collect().sort("ts_recv", "sequence")

    assert read.height == sum(
        FIXTURE_ENTRIES[digest.path]["rows"] for digest in snapshot.partitions
    )
    assert_frame_equal(read, scanned)


def test_reading_a_snapshot_refuses_a_partition_that_changed_after_it(tmp_path: Path) -> None:
    store = store_with_the_es_trades(tmp_path)
    pinned = store.snapshot(ES_TRADES)
    shorter = store.scan_partition(TRADES_OF_MARCH_6).collect().head(-1)

    store.write_partition(TRADES_OF_MARCH_6, shorter)

    with pytest.raises(ValueError, match="the file changed after the snapshot"):
        store.read(pinned)


def test_reading_a_snapshot_refuses_metadata_that_changed_after_it(tmp_path: Path) -> None:
    store = store_with_the_es_trades(tmp_path)
    pinned = store.snapshot(ES_TRADES)
    mini_lots = DatasetMetadata(
        size_unit=SizeUnit(lot=Decimal("0.1"), asset="contract"),
        origin=DatasetOrigin.IMPORT,
        licence_scope=NO_LICENCE,
    )

    store.write_dataset_metadata(ES_TRADES.dataset, mini_lots)

    with pytest.raises(ValueError, match="the file changed after the snapshot"):
        store.read(pinned)


def test_reading_a_snapshot_keeps_only_the_bars_of_its_dates() -> None:
    minute_bars = Dataset(
        provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES"
    )
    request = PartitionRequest(dataset=minute_bars, start=date(2026, 3, 6), end=date(2026, 3, 6))

    read = FIXTURE_STORE.read(FIXTURE_STORE.snapshot(request))

    assert read.height > 0
    assert read.get_column("trade_date").unique().to_list() == [date(2026, 3, 6)]
    assert read.filter(pl.col("trade_date") != date(2026, 3, 6)).is_empty()


def test_the_pinned_metadata_is_the_one_the_snapshot_pinned(tmp_path: Path) -> None:
    store = store_with_the_es_trades(tmp_path)
    pinned = store.snapshot(ES_TRADES)
    mini_lots = DatasetMetadata(
        size_unit=SizeUnit(lot=Decimal("0.1"), asset="contract"),
        origin=DatasetOrigin.IMPORT,
        licence_scope=NO_LICENCE,
    )

    assert store.pinned_metadata(pinned) == ES_SIZE
    store.write_dataset_metadata(ES_TRADES.dataset, mini_lots)
    with pytest.raises(ValueError, match="the file changed after the snapshot"):
        store.pinned_metadata(pinned)


def test_a_snapshot_read_back_with_a_partition_twice_is_refused() -> None:
    snapshot = FIXTURE_STORE.snapshot(ES_TRADES)
    twice = (snapshot.partitions[0], snapshot.partitions[0])

    with pytest.raises(ValueError, match="Expected the partitions sorted by path, each once"):
        Snapshot.of(ES_TRADES, snapshot.metadata, twice)


def test_a_snapshot_refuses_metadata_it_cannot_read(tmp_path: Path) -> None:
    store = store_with_the_es_trades(tmp_path)
    (tmp_path / ES_TRADES.dataset.metadata_path()).write_text('{"size_unit": {}}', "utf-8")

    with pytest.raises(ValueError, match=r"dataset\.json to hold a DatasetMetadata"):
        store.snapshot(ES_TRADES)


@pytest.mark.parametrize("root", ["ES", "BTCUSDT-PERP"])
@pytest.mark.parametrize("schema", ["trades", "ohlcv-1s", "ohlcv-1m"])
def test_a_read_cut_at_any_date_holds_exactly_the_rows_available_before_the_next_open(
    root: str, schema: str
) -> None:
    # Every row available by the close of the cut's last session, and the rows received in the
    # break after it, which are the planted print of ES's 2026-03-06 and its bars, and no other.
    # A bar is available at its close, so one closing as the next session opens belongs to the
    # session before, while a print received at that instant is the next session's.
    dataset = Dataset(provider="synthetic", schema_name=parse_schema_name(schema), root=root)
    ends = SESSION_ENDS[root]
    first, last = min(ends), max(ends)
    trades = schema == "trades"
    clock, order = ("ts_recv", ["ts_recv", "sequence"]) if trades else ("ts_close", ["ts_open"])

    def read(start: date, end: date) -> pl.DataFrame:
        request = PartitionRequest(dataset=dataset, start=start, end=end)
        return FIXTURE_STORE.read(FIXTURE_STORE.snapshot(request)).sort(order)

    every_row = read(first, last)
    for offset in range((last - first).days + 1):
        cut = first + timedelta(days=offset)
        session = max(day for day in ends if day <= cut)
        close, next_open = (int(instant.timestamp()) * 1_000_000_000 for instant in ends[session])
        before_the_next_open = pl.col(clock) < next_open if trades else pl.col(clock) <= next_open
        available = every_row.filter(before_the_next_open)
        in_the_break = available.filter(pl.col(clock) > close)
        assert_frame_equal(read(first, cut), available)
        assert in_the_break.height == int((root, session) == SESSION_WITH_A_PRINT_IN_THE_BREAK)
        if not trades and cut in ends:
            assert_frame_equal(read(cut, last), every_row.filter(pl.col("trade_date") >= cut))


def digest_beside(path: Path) -> Path:
    return path.with_suffix(DIGEST_SUFFIX)


def write_digest(path: Path, sha256: str, size_change: int = 0, time_change: int = 0) -> None:
    status = path.stat()
    planted = FileDigestRecord(
        size_bytes=status.st_size + size_change,
        modified_ns=status.st_mtime_ns + time_change,
        sha256=sha256,
    )
    digest_beside(path).write_text(planted.model_dump_json(), encoding="utf-8")


def pinned_sha256(snapshot: Snapshot, partition: Partition) -> str:
    path = partition.relative_path().as_posix()
    return next(digest.sha256 for digest in snapshot.partitions if digest.path == path)


def test_a_written_partition_keeps_its_digest_beside_it(tmp_path: Path) -> None:
    store_with_the_es_trades(tmp_path)
    path = tmp_path / TRADES_OF_MARCH_5.relative_path()
    status = path.stat()

    recorded = FileDigestRecord.model_validate_json(digest_beside(path).read_bytes())

    assert recorded == FileDigestRecord(
        size_bytes=status.st_size,
        modified_ns=status.st_mtime_ns,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def test_a_snapshot_pins_a_current_digest_without_reading_its_file_and_a_read_checks_it(
    tmp_path: Path,
) -> None:
    # The planted digest describes the file by size and time but holds a hash no file has, so
    # only a snapshot that took it without reading the file pins that hash.
    store = store_with_the_es_trades(tmp_path)
    write_digest(tmp_path / TRADES_OF_MARCH_5.relative_path(), UNKNOWN_SHA256)

    snapshot = store.snapshot(ES_TRADES)

    assert pinned_sha256(snapshot, TRADES_OF_MARCH_5) == UNKNOWN_SHA256
    with pytest.raises(ValueError, match="the file changed after the snapshot"):
        store.read(snapshot)


@pytest.mark.parametrize(("size_change", "time_change"), [(1, 0), (0, 1)])
def test_a_digest_whose_size_or_time_differ_from_its_file_is_passed_over(
    tmp_path: Path, size_change: int, time_change: int
) -> None:
    store = store_with_the_es_trades(tmp_path)
    path = tmp_path / TRADES_OF_MARCH_5.relative_path()
    write_digest(path, UNKNOWN_SHA256, size_change, time_change)

    snapshot = store.snapshot(ES_TRADES)

    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert pinned_sha256(snapshot, TRADES_OF_MARCH_5) == actual


def test_a_snapshot_writes_no_digest(tmp_path: Path) -> None:
    store = store_with_the_es_trades(tmp_path)
    for partition in (TRADES_OF_MARCH_5, TRADES_OF_MARCH_6):
        digest_beside(tmp_path / partition.relative_path()).unlink()
    files = sorted(tmp_path.rglob("*"))

    store.snapshot(ES_TRADES)

    assert sorted(tmp_path.rglob("*")) == files


def test_recording_digests_writes_those_missing_and_pins_what_a_snapshot_pins(
    tmp_path: Path,
) -> None:
    store = store_with_the_es_trades(tmp_path)
    paths = [
        tmp_path / partition.relative_path() for partition in (TRADES_OF_MARCH_5, TRADES_OF_MARCH_6)
    ]
    for path in paths:
        digest_beside(path).unlink()
    pinned = store.snapshot(ES_TRADES)

    recorded = store.record_digests(ES_TRADES)

    assert recorded == pinned
    for path in paths:
        written = FileDigestRecord.model_validate_json(digest_beside(path).read_bytes())
        assert written.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_digest_that_does_not_parse_is_refused_with_its_path(tmp_path: Path) -> None:
    store = store_with_the_es_trades(tmp_path)
    digest_beside(tmp_path / TRADES_OF_MARCH_5.relative_path()).write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match=r"Expected .*part\.digest\.json to hold a FileDigest"):
        store.snapshot(ES_TRADES)


def test_one_pinned_partition_reads_alone_cut_to_the_dates_of_its_snapshot() -> None:
    minute_bars = Dataset(
        provider="synthetic", schema_name=parse_schema_name("ohlcv-1m"), root="ES"
    )
    request = PartitionRequest(dataset=minute_bars, start=date(2026, 3, 6), end=date(2026, 3, 6))
    snapshot = FIXTURE_STORE.snapshot(request)
    first = snapshot.partitions[0]

    read = FIXTURE_STORE.read_pinned_partition(snapshot, first)

    partition = Partition.from_relative_path(PurePosixPath(first.path))
    whole = FIXTURE_STORE.scan_partition(partition).collect()
    assert read.height > 0
    assert_frame_equal(read, whole.filter(pl.col("trade_date") == date(2026, 3, 6)))


def test_a_partition_its_snapshot_does_not_pin_is_refused(tmp_path: Path) -> None:
    store = store_with_the_es_trades(tmp_path)
    one_day = PartitionRequest(
        dataset=ES_TRADES.dataset, start=date(2026, 3, 5), end=date(2026, 3, 5)
    )
    snapshot = store.snapshot(one_day)
    other = store.snapshot(ES_TRADES).partitions[-1]

    with pytest.raises(ValueError, match="Expected a partition the snapshot"):
        store.read_pinned_partition(snapshot, other)
