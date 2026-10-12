import hashlib
import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path, PurePosixPath

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from fefat.market.layout import Dataset, DatasetMetadata, Partition, SizeUnit
from fefat.market.schema import SchemaKind, parse_schema_name
from fefat.market.store import (
    BatchJob,
    PartitionRequest,
    RawFile,
    RawManifest,
    Snapshot,
    Store,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
FIXTURE_STORE = Store(FIXTURES)
MANIFEST_ENTRIES = {
    f"synthetic/{entry['path']}": entry
    for entry in json.loads((FIXTURES / "synthetic" / "MANIFEST.json").read_text("utf-8"))["files"]
    if entry["path"].endswith(".parquet")
}
ES_TRADES = PartitionRequest(
    dataset=Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="ES"),
    start=date(2026, 3, 5),
    end=date(2026, 3, 9),
)
ES_SIZE = DatasetMetadata(size_unit=SizeUnit(lot=Decimal(1), asset="contract"))
TRADES_OF_MARCH_5 = Partition.from_relative_path(
    PurePosixPath("synthetic/trades/root=ES/contract=ESH6/date=2026-03-05/part.parquet")
)
TRADES_OF_MARCH_6 = Partition.from_relative_path(
    PurePosixPath("synthetic/trades/root=ES/contract=ESH6/date=2026-03-06/part.parquet")
)
MINUTE_BARS_OF_MARCH = Partition.from_relative_path(
    PurePosixPath("synthetic/ohlcv-1m/root=ES/contract=ESH6/month=2026-03/part.parquet")
)
SETTLEMENTS = Partition.from_relative_path(
    PurePosixPath("synthetic/statistics/root=ES/contract=ESH6/part.parquet")
)
ORDER_BY_KIND = {SchemaKind.TRADES: ["ts_recv", "sequence"], SchemaKind.OHLCV: ["ts_open"]}
SNAPSHOT_PROGRAM = """
import sys
from pathlib import Path

from fefat.market.store import PartitionRequest, Store

request = PartitionRequest.model_validate_json(sys.argv[2])
sys.stdout.write(Store(Path(sys.argv[1])).snapshot(request).model_dump_json())
"""
RAW_PATH = PurePosixPath("vendor/job-1/bars.dbn")
RAW_BYTES = b"vendor bytes"
JOB = BatchJob(job_id="job-1", published_sha256=hashlib.sha256(RAW_BYTES).hexdigest())


def in_order(frame: pl.DataFrame, partition: Partition) -> pl.DataFrame:
    return frame.sort(ORDER_BY_KIND[partition.dataset.schema_name.kind])


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


def store_with_a_raw_file(folder: Path) -> Store:
    path = folder / "raw" / RAW_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(RAW_BYTES)
    return Store(folder)


def record(store: Store, vendor_version: str = "DBN 3") -> RawFile:
    return store.record_raw_file(
        RAW_PATH,
        provider="vendor",
        vendor_version=vendor_version,
        downloaded_on=date(2026, 9, 23),
        batch_job=JOB,
    )


@pytest.fixture(scope="module")
def copied_store(tmp_path_factory: pytest.TempPathFactory) -> Store:
    store = Store(tmp_path_factory.mktemp("store"))
    for file in FIXTURE_STORE.list_partitions():
        dataset = file.partition.dataset
        store.write_dataset_metadata(dataset, FIXTURE_STORE.dataset_metadata(dataset))
        store.write_partition(
            file.partition, FIXTURE_STORE.scan_partition(file.partition).collect()
        )
    return store


@pytest.mark.parametrize("path", sorted(MANIFEST_ENTRIES))
def test_every_synthetic_partition_round_trips_through_the_store(
    copied_store: Store, path: str
) -> None:
    partition = Partition.from_relative_path(PurePosixPath(path))

    written = copied_store.scan_partition(partition).collect()
    fixture = pl.read_parquet(FIXTURES / path)

    assert written.height == MANIFEST_ENTRIES[path]["rows"]
    assert_frame_equal(in_order(written, partition), in_order(fixture, partition))
    assert copied_store.dataset_metadata(partition.dataset) == FIXTURE_STORE.dataset_metadata(
        partition.dataset
    )


def test_the_fixture_store_lists_each_synthetic_partition_with_its_size() -> None:
    files = FIXTURE_STORE.list_partitions()
    paths = [file.partition.relative_path().as_posix() for file in files]

    assert {path: file.size_bytes for path, file in zip(paths, files, strict=True)} == {
        path: entry["bytes"] for path, entry in MANIFEST_ENTRIES.items()
    }
    assert paths == sorted(paths)
    assert len(paths) == 10


def test_a_store_whose_folder_does_not_exist_yet_lists_nothing_and_creates_nothing(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "not-yet"

    assert Store(folder).list_partitions() == ()
    assert not folder.exists()


def test_a_request_reads_the_partitions_of_its_dates_and_no_others() -> None:
    request = PartitionRequest(
        dataset=ES_TRADES.dataset, start=date(2026, 3, 5), end=date(2026, 3, 6)
    )
    expected_rows = sum(
        MANIFEST_ENTRIES[partition.relative_path().as_posix()]["rows"]
        for partition in (TRADES_OF_MARCH_5, TRADES_OF_MARCH_6)
    )

    assert FIXTURE_STORE.scan(request).collect().height == expected_rows


@pytest.mark.parametrize(
    ("partition", "start", "end", "expected"),
    [
        (TRADES_OF_MARCH_5, date(2026, 3, 5), date(2026, 3, 5), True),
        (TRADES_OF_MARCH_5, date(2026, 3, 6), date(2026, 3, 9), False),
        (TRADES_OF_MARCH_5, date(2026, 3, 1), date(2026, 3, 4), False),
        (MINUTE_BARS_OF_MARCH, date(2026, 2, 20), date(2026, 3, 1), True),
        (MINUTE_BARS_OF_MARCH, date(2026, 4, 1), date(2026, 4, 30), False),
        (SETTLEMENTS, date(2010, 6, 6), date(2010, 6, 6), True),
    ],
)
def test_a_request_selects_the_partitions_whose_key_touches_its_dates(
    partition: Partition, start: date, end: date, expected: bool
) -> None:
    request = PartitionRequest(dataset=partition.dataset, start=start, end=end)

    assert request.selects(partition) is expected


def test_a_request_selects_nothing_of_another_dataset() -> None:
    btc_trades = Dataset(provider="synthetic", schema_name=parse_schema_name("trades"), root="BTC")
    request = PartitionRequest(dataset=btc_trades, start=date(2026, 3, 1), end=date(2026, 3, 31))

    assert not request.selects(TRADES_OF_MARCH_5)


def test_a_request_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(ValueError, match="Expected the start"):
        PartitionRequest(dataset=ES_TRADES.dataset, start=date(2026, 3, 9), end=date(2026, 3, 5))


def test_a_request_that_selects_nothing_is_refused() -> None:
    request = PartitionRequest(
        dataset=ES_TRADES.dataset, start=date(2025, 1, 1), end=date(2025, 1, 31)
    )

    with pytest.raises(ValueError, match="Expected at least one partition"):
        FIXTURE_STORE.scan(request)
    with pytest.raises(ValueError, match="Expected at least one partition"):
        FIXTURE_STORE.snapshot(request)


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


def test_a_snapshot_pins_each_partitions_sha256_and_hashes_their_sha256sum_listing() -> None:
    snapshot = FIXTURE_STORE.snapshot(ES_TRADES)
    listing = "".join(f"{digest.sha256}  {digest.path}\n" for digest in snapshot.partitions)

    assert {digest.path: (digest.size_bytes, digest.sha256) for digest in snapshot.partitions} == {
        path: (entry["bytes"], entry["sha256"])
        for path, entry in MANIFEST_ENTRIES.items()
        if path.startswith("synthetic/trades/root=ES/")
    }
    assert [digest.path for digest in snapshot.partitions] == sorted(
        digest.path for digest in snapshot.partitions
    )
    assert snapshot.sha256 == hashlib.sha256(listing.encode()).hexdigest()


def test_a_snapshot_whose_hash_does_not_cover_its_partitions_is_refused() -> None:
    snapshot = FIXTURE_STORE.snapshot(ES_TRADES)

    with pytest.raises(ValueError, match="Expected the snapshot hash"):
        Snapshot(
            request=snapshot.request, partitions=snapshot.partitions[:-1], sha256=snapshot.sha256
        )


def test_a_frame_with_other_columns_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    store = Store(tmp_path)
    store.write_dataset_metadata(ES_TRADES.dataset, ES_SIZE)
    trades = FIXTURE_STORE.scan_partition(TRADES_OF_MARCH_5).collect()
    wrong_frames = [
        trades.drop("side"),
        trades.with_columns(pl.col("price").cast(pl.Float64)),
        trades.select(list(reversed(trades.columns))),
    ]

    for wrong in wrong_frames:
        with pytest.raises(ValueError, match="Expected the columns"):
            store.write_partition(TRADES_OF_MARCH_5, wrong)
    assert store.list_partitions() == ()


def test_a_partition_of_a_dataset_without_metadata_is_refused(tmp_path: Path) -> None:
    store = Store(tmp_path)
    trades = FIXTURE_STORE.scan_partition(TRADES_OF_MARCH_5).collect()

    with pytest.raises(FileNotFoundError, match="Expected the metadata"):
        store.write_partition(TRADES_OF_MARCH_5, trades)
    assert store.list_partitions() == ()


def test_a_partition_file_that_drifted_from_its_schema_is_refused_when_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / TRADES_OF_MARCH_5.relative_path()
    path.parent.mkdir(parents=True)
    pl.DataFrame({"price": [1]}).write_parquet(path)

    with pytest.raises(ValueError, match="Expected the columns"):
        Store(tmp_path).scan_partition(TRADES_OF_MARCH_5)


def test_a_failed_write_keeps_the_old_partition_and_leaves_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = store_with_the_es_trades(tmp_path)
    path = tmp_path / TRADES_OF_MARCH_5.relative_path()
    before = path.read_bytes()
    trades = store.scan_partition(TRADES_OF_MARCH_5).collect()

    def write_half_then_fail(frame: pl.DataFrame, file: Path, **options: object) -> None:
        Path(file).write_bytes(b"half a file")
        raise OSError("the disk filled up")

    monkeypatch.setattr(pl.DataFrame, "write_parquet", write_half_then_fail)
    with pytest.raises(OSError, match="the disk filled up"):
        store.write_partition(TRADES_OF_MARCH_5, trades.head(10))

    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]


def test_dataset_metadata_reads_back_as_written(tmp_path: Path) -> None:
    store = Store(tmp_path)
    btc = DatasetMetadata(size_unit=SizeUnit(lot=Decimal("0.001"), asset="BTC"))

    store.write_dataset_metadata(ES_TRADES.dataset, btc)

    assert store.dataset_metadata(ES_TRADES.dataset) == btc
    assert (
        b"\r\n"
        not in (tmp_path / ES_TRADES.dataset.relative_folder() / "dataset.json").read_bytes()
    )


def test_recording_a_raw_file_keeps_its_size_hash_and_vendor_details(tmp_path: Path) -> None:
    store = store_with_a_raw_file(tmp_path)

    recorded = record(store)

    manifest = (tmp_path / "raw" / "MANIFEST.json").read_bytes()
    assert recorded == RawFile(
        path="vendor/job-1/bars.dbn",
        size_bytes=len(RAW_BYTES),
        sha256=hashlib.sha256(RAW_BYTES).hexdigest(),
        provider="vendor",
        vendor_version="DBN 3",
        downloaded_on=date(2026, 9, 23),
        batch_job=JOB,
    )
    assert store.raw_manifest() == RawManifest(files=(recorded,))
    assert b"\r\n" not in manifest
    assert manifest.endswith(b"}\n")


def test_recording_the_same_raw_file_again_changes_nothing(tmp_path: Path) -> None:
    store = store_with_a_raw_file(tmp_path)
    first = record(store)
    manifest = (tmp_path / "raw" / "MANIFEST.json").read_bytes()

    assert record(store) == first
    assert (tmp_path / "raw" / "MANIFEST.json").read_bytes() == manifest


def test_a_raw_file_whose_bytes_changed_is_refused_with_both_hashes(tmp_path: Path) -> None:
    store = store_with_a_raw_file(tmp_path)
    first = record(store)
    (tmp_path / "raw" / RAW_PATH).write_bytes(b"re-normalised vendor bytes")
    changed = hashlib.sha256(b"re-normalised vendor bytes").hexdigest()

    with pytest.raises(ValueError, match=f"{first.sha256}.*{changed}"):
        record(store)
    assert store.raw_manifest() == RawManifest(files=(first,))


def test_a_raw_file_recorded_again_with_other_details_is_refused(tmp_path: Path) -> None:
    store = store_with_a_raw_file(tmp_path)
    first = record(store)

    with pytest.raises(ValueError, match="Expected the raw file"):
        record(store, vendor_version="DBN 2")
    assert store.raw_manifest() == RawManifest(files=(first,))


def test_recording_a_raw_file_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Expected the raw file"):
        record(Store(tmp_path))


@pytest.mark.parametrize(
    "path", ["../outside.dbn", "vendor/../../outside.dbn", "/vendor/bars.dbn", "C:/bars.dbn", "."]
)
def test_a_raw_path_that_leaves_the_raw_folder_is_refused(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError, match="Expected a path inside the raw folder"):
        Store(tmp_path).record_raw_file(
            PurePosixPath(path),
            provider="vendor",
            vendor_version="DBN 3",
            downloaded_on=date(2026, 9, 23),
            batch_job=None,
        )


def test_a_published_hash_is_bare_lowercase_hex() -> None:
    with pytest.raises(ValueError, match="pattern"):
        BatchJob(job_id="job-1", published_sha256=f"sha256:{JOB.published_sha256}")
