import hashlib
import json
import os
import shutil
from collections.abc import Callable
from datetime import date
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
from fefat.market.raw_manifest import BatchJob, RawFile, RawManifest
from fefat.market.schema import SchemaKind, parse_schema_name
from fefat.market.store import Store
from fefat.market.store_files import DIGEST_SUFFIX, FileDigestRecord

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
SECONDS_OF_MARCH_5 = Partition.from_relative_path(
    PurePosixPath("synthetic/ohlcv-1s/root=ES/contract=ESH2026/date=2026-03-05/part.parquet")
)
SECONDS_OF_MARCH_6 = Partition.from_relative_path(
    PurePosixPath("synthetic/ohlcv-1s/root=ES/contract=ESH2026/date=2026-03-06/part.parquet")
)
MINUTE_BARS_OF_MARCH = Partition.from_relative_path(
    PurePosixPath("synthetic/ohlcv-1m/root=ES/contract=ESH2026/month=2026-03/part.parquet")
)
FIVE_MINUTE_BARS = Partition.from_relative_path(
    PurePosixPath("synthetic/ohlcv-5m/root=ES/contract=ESH2026/part.parquet")
)
ORDER_BY_KIND = {
    SchemaKind.TRADES: ["ts_recv", "sequence"],
    SchemaKind.OHLCV: ["ts_open"],
    SchemaKind.FUNDING: ["ts_recv"],
}
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


def store_with_a_raw_file(folder: Path) -> Store:
    path = folder / "raw" / RAW_PATH
    path.parent.mkdir(parents=True)
    path.write_bytes(RAW_BYTES)
    return Store(folder)


def record(
    store: Store, vendor_version: str = "DBN 3", imported_on: date = date(2026, 10, 13)
) -> RawFile:
    return store.raw.record(
        RAW_PATH,
        provider="vendor",
        vendor_version=vendor_version,
        downloaded_on=date(2026, 9, 23),
        batch_job=JOB,
        imported_on=imported_on,
        roots=("ES", "MES"),
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
    assert len(paths) == 18


def test_a_store_whose_folder_does_not_exist_yet_lists_nothing_and_creates_nothing(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "not-yet"

    assert Store(folder).list_partitions() == ()
    assert Store(folder).list_datasets() == ()
    assert not folder.exists()


def test_the_fixture_store_lists_its_datasets_from_their_folders() -> None:
    folders = [dataset.relative_folder().as_posix() for dataset in FIXTURE_STORE.list_datasets()]

    assert folders == [
        "synthetic/funding/root=BTCUSDT-PERP",
        "synthetic/ohlcv-1m/root=BTCUSDT-PERP",
        "synthetic/ohlcv-1m/root=ES",
        "synthetic/ohlcv-1s/root=BTCUSDT-PERP",
        "synthetic/ohlcv-1s/root=ES",
        "synthetic/trades/root=BTCUSDT-PERP",
        "synthetic/trades/root=ES",
    ]


def test_listing_one_dataset_lists_its_partitions_and_no_others() -> None:
    files = FIXTURE_STORE.list_partitions(ES_TRADES.dataset)

    assert files == tuple(
        file
        for file in FIXTURE_STORE.list_partitions()
        if file.partition.dataset == ES_TRADES.dataset
    )
    assert len(files) == 6


def test_the_raw_and_reports_folders_beside_the_providers_hold_no_dataset(tmp_path: Path) -> None:
    # A copy of the dataset's files under each folder, as if it were a provider.
    store = store_with_the_es_trades(tmp_path)
    for reserved in ("raw", "reports"):
        for relative in (ES_TRADES.dataset.metadata_path(), TRADES_OF_MARCH_5.relative_path()):
            copy = tmp_path / reserved / PurePosixPath(*relative.parts[1:])
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(tmp_path / relative, copy)

    assert store.list_datasets() == (ES_TRADES.dataset,)
    assert [file.partition for file in store.list_partitions()] == [
        TRADES_OF_MARCH_5,
        TRADES_OF_MARCH_6,
    ]


def test_a_request_reads_the_trades_of_its_dates_and_no_others() -> None:
    request = PartitionRequest(
        dataset=ES_TRADES.dataset, start=date(2026, 3, 5), end=date(2026, 3, 6)
    )
    expected_rows = sum(
        MANIFEST_ENTRIES[f"synthetic/trades/root=ES/contract={contract}/date={day}/part.parquet"][
            "rows"
        ]
        for contract in ("ESH2026", "ESM2026")
        for day in ("2026-03-05", "2026-03-06")
    )

    assert FIXTURE_STORE.scan(request).collect().height == expected_rows


def test_a_scan_of_contracts_labels_each_row_with_the_contract_of_its_partition() -> None:
    request = PartitionRequest(
        dataset=MINUTE_BARS_OF_MARCH.dataset, start=date(2026, 3, 6), end=date(2026, 3, 9)
    )

    labelled = FIXTURE_STORE.scan_contracts(request).collect()

    assert_frame_equal(labelled.drop("contract"), FIXTURE_STORE.scan(request).collect())
    assert labelled.columns[-1] == "contract"
    assert labelled.select("contract", "instrument_id").unique().sort("contract").rows() == [
        ("ESH2026", 1001),
        ("ESM2026", 1003),
    ]


def test_a_scan_of_a_month_is_unchanged_when_later_trade_dates_join_it(tmp_path: Path) -> None:
    every_day = FIXTURE_STORE.scan_partition(MINUTE_BARS_OF_MARCH).collect()
    dataset = MINUTE_BARS_OF_MARCH.dataset
    request = PartitionRequest(dataset=dataset, start=date(2026, 3, 5), end=date(2026, 3, 6))
    store = Store(tmp_path)
    store.write_dataset_metadata(dataset, ES_SIZE)
    earlier_days = every_day.filter(pl.col("trade_date") <= request.end)
    store.write_partition(MINUTE_BARS_OF_MARCH, earlier_days)
    before = store.scan(request).collect().sort("ts_open")

    store.write_partition(MINUTE_BARS_OF_MARCH, every_day)
    after = store.scan(request).collect().sort("ts_open")

    assert every_day.filter(pl.col("trade_date") > request.end).height > 0
    assert after.filter(pl.col("trade_date") > request.end).is_empty()
    assert_frame_equal(after, before)


def test_a_request_that_selects_nothing_is_refused() -> None:
    request = PartitionRequest(
        dataset=ES_TRADES.dataset, start=date(2025, 1, 1), end=date(2025, 1, 31)
    )

    with pytest.raises(ValueError, match="Expected at least one partition"):
        FIXTURE_STORE.scan(request)
    with pytest.raises(ValueError, match="Expected at least one partition"):
        FIXTURE_STORE.snapshot(request)


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


def april_first_on_the_last_bar(bars: pl.DataFrame) -> pl.DataFrame:
    last_bar = pl.int_range(pl.len()) == pl.len() - 1
    april_first = pl.when(last_bar).then(pl.lit(date(2026, 4, 1))).otherwise(pl.col("trade_date"))
    return bars.with_columns(april_first.alias("trade_date"))


@pytest.mark.parametrize(
    ("partition", "source", "change"),
    [
        (MINUTE_BARS_OF_MARCH, MINUTE_BARS_OF_MARCH, april_first_on_the_last_bar),
        (SECONDS_OF_MARCH_6, SECONDS_OF_MARCH_5, lambda bars: bars),
        (
            SECONDS_OF_MARCH_5,
            SECONDS_OF_MARCH_5,
            lambda bars: bars.with_columns(pl.lit(None, dtype=pl.Date).alias("trade_date")),
        ),
        (
            FIVE_MINUTE_BARS,
            MINUTE_BARS_OF_MARCH,
            lambda bars: bars.with_columns(pl.lit(None, dtype=pl.Date).alias("trade_date")),
        ),
    ],
)
def test_a_bar_outside_its_partitions_trade_date_or_month_is_refused(
    tmp_path: Path,
    partition: Partition,
    source: Partition,
    change: Callable[[pl.DataFrame], pl.DataFrame],
) -> None:
    store = Store(tmp_path)
    store.write_dataset_metadata(partition.dataset, ES_SIZE)
    bars = change(FIXTURE_STORE.scan_partition(source).collect())

    with pytest.raises(ValueError, match="Expected every bar"):
        store.write_partition(partition, bars)
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

    digest = path.with_suffix(DIGEST_SUFFIX)
    assert path.read_bytes() == before
    assert sorted(path.parent.iterdir()) == [digest, path]
    assert FileDigestRecord.model_validate_json(digest.read_bytes()).sha256 == (
        hashlib.sha256(before).hexdigest()
    )


def test_a_write_is_flushed_to_disk_before_it_replaces_its_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path)
    store.write_dataset_metadata(ES_TRADES.dataset, ES_SIZE)
    target = tmp_path / TRADES_OF_MARCH_5.relative_path()
    digest = target.with_suffix(DIGEST_SUFFIX)
    targets_at_each_flush: list[tuple[bool, bool]] = []
    flush = os.fsync

    def recording_flush(descriptor: int) -> None:
        targets_at_each_flush.append((target.exists(), digest.exists()))
        flush(descriptor)

    monkeypatch.setattr(os, "fsync", recording_flush)
    store.write_partition(
        TRADES_OF_MARCH_5, FIXTURE_STORE.scan_partition(TRADES_OF_MARCH_5).collect()
    )

    assert targets_at_each_flush == [(False, False), (True, False)]
    assert target.exists()
    assert digest.exists()


def test_dataset_metadata_reads_back_as_written(tmp_path: Path) -> None:
    store = Store(tmp_path)
    btc = DatasetMetadata(
        size_unit=SizeUnit(lot=Decimal("0.001"), asset="BTC"),
        origin=DatasetOrigin.IMPORT,
        licence_scope=NO_LICENCE,
    )

    store.write_dataset_metadata(ES_TRADES.dataset, btc)

    written = (tmp_path / ES_TRADES.dataset.metadata_path()).read_bytes()
    assert store.dataset_metadata(ES_TRADES.dataset) == btc
    assert b"\r\n" not in written


def test_a_broken_dataset_json_is_refused_with_its_path(tmp_path: Path) -> None:
    path = tmp_path / ES_TRADES.dataset.metadata_path()
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"size_unit": {"lot": "-1", "asset": "contract"}, "origin": "import", '
        '"licence_scope": "Synthetic test data; no licence applies"}',
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match=r"Expected .*dataset\.json to hold a DatasetMetadata.*\n.*size_unit.lot"
    ):
        Store(tmp_path).dataset_metadata(ES_TRADES.dataset)


def test_a_dataset_json_written_before_origins_and_licence_scopes_is_refused(
    tmp_path: Path,
) -> None:
    # Step 1.9 added both fields: a store written earlier gets them by importing its files
    # again, or by the rewrite docs/data-inventory.md records.
    path = tmp_path / ES_TRADES.dataset.metadata_path()
    path.parent.mkdir(parents=True)
    path.write_text('{"size_unit": {"lot": "1", "asset": "contract"}}', encoding="utf-8")

    with pytest.raises(ValueError, match=r"(?s)dataset\.json.*origin\n  Field required.*licence"):
        Store(tmp_path).dataset_metadata(ES_TRADES.dataset)


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
        imported_on=date(2026, 10, 13),
        roots=("ES", "MES"),
    )
    assert store.raw.manifest() == RawManifest(files=(recorded,))
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
    assert store.raw.manifest() == RawManifest(files=(first,))


def test_a_raw_file_recorded_again_with_other_details_is_refused(tmp_path: Path) -> None:
    store = store_with_a_raw_file(tmp_path)
    first = record(store)

    with pytest.raises(ValueError, match="Expected the raw file"):
        record(store, vendor_version="DBN 2")
    with pytest.raises(ValueError, match="Expected the raw file"):
        record(store, imported_on=date(2026, 10, 16))
    assert store.raw.manifest() == RawManifest(files=(first,))


def test_the_last_import_of_a_root_is_its_newest_file_from_the_provider() -> None:
    def imported(path: str, provider: str, day: int, *roots: str) -> RawFile:
        return RawFile(
            path=path,
            size_bytes=1,
            sha256="0" * 64,
            provider=provider,
            vendor_version="DBN 3",
            downloaded_on=date(2026, 9, 23),
            batch_job=None,
            imported_on=date(2026, 10, day),
            roots=roots,
        )

    manifest = RawManifest(
        files=(
            imported("vendor/a.dbn", "vendor", 13, "ES", "MES"),
            imported("vendor/b.dbn", "vendor", 15, "MES"),
            imported("vendor/b.json", "vendor", 16),
            imported("other/c.dbn", "other", 17, "ES"),
        )
    )

    assert manifest.last_import("vendor", "ES") == date(2026, 10, 13)
    assert manifest.last_import("vendor", "MES") == date(2026, 10, 15)
    assert manifest.last_import("vendor", "MNQ") is None


def test_recording_a_raw_file_that_does_not_exist_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Expected the raw file"):
        record(Store(tmp_path))


@pytest.mark.parametrize(
    "path",
    [
        "../outside.dbn",
        "vendor/../../outside.dbn",
        "/vendor/bars.dbn",
        "C:/bars.dbn",
        ".",
        "MANIFEST.json",
        "manifest.json",
        "MANIFEST.json.",
        "vendor./bars.dbn",
        "vendor/bars.dbn ",
    ],
)
def test_a_raw_path_that_leaves_the_raw_folder_or_names_the_manifest_is_refused(
    tmp_path: Path, path: str
) -> None:
    with pytest.raises(ValueError, match="Expected a vendor's file inside the raw folder"):
        Store(tmp_path).raw.record(
            PurePosixPath(path),
            provider="vendor",
            vendor_version="DBN 3",
            downloaded_on=date(2026, 9, 23),
            batch_job=None,
            imported_on=date(2026, 10, 13),
            roots=(),
        )


def test_another_name_of_the_raw_manifest_is_refused(tmp_path: Path) -> None:
    store = store_with_a_raw_file(tmp_path)
    record(store)
    os.link(tmp_path / "raw" / "MANIFEST.json", tmp_path / "raw" / "vendor" / "alias.json")

    with pytest.raises(ValueError, match="another name of the raw manifest"):
        store.raw.record(
            PurePosixPath("vendor/alias.json"),
            provider="vendor",
            vendor_version="DBN 3",
            downloaded_on=date(2026, 9, 23),
            batch_job=None,
            imported_on=date(2026, 10, 13),
            roots=(),
        )


def test_a_broken_raw_manifest_is_refused_with_its_path(tmp_path: Path) -> None:
    store = store_with_a_raw_file(tmp_path)
    (tmp_path / "raw" / "MANIFEST.json").write_text('{"files": [{"path": "x"}]}', "utf-8")

    with pytest.raises(ValueError, match=r"Expected .*MANIFEST\.json to hold a RawManifest"):
        store.raw.manifest()


def test_a_published_hash_is_bare_lowercase_hex() -> None:
    with pytest.raises(ValueError, match="pattern"):
        BatchJob(job_id="job-1", published_sha256=f"sha256:{JOB.published_sha256}")


def test_a_vendor_file_is_copied_into_raw_once_its_copy_has_the_stated_hash(
    tmp_path: Path,
) -> None:
    source = tmp_path / "download" / "bars.dbn"
    source.parent.mkdir()
    source.write_bytes(RAW_BYTES)
    store = Store(tmp_path / "store")

    store.raw.write(RAW_PATH, source, JOB.published_sha256)

    assert (tmp_path / "store" / "raw" / RAW_PATH).read_bytes() == RAW_BYTES
    assert store.raw.manifest() == RawManifest()


def test_a_copy_without_the_stated_hash_is_refused_and_left_out(tmp_path: Path) -> None:
    source = tmp_path / "bars.dbn"
    source.write_bytes(b"other vendor bytes")
    store = Store(tmp_path / "store")

    with pytest.raises(ValueError, match=f"SHA-256 {JOB.published_sha256}, got"):
        store.raw.write(RAW_PATH, source, JOB.published_sha256)

    assert not (tmp_path / "store" / "raw" / RAW_PATH).exists()


def test_a_raw_file_the_manifest_records_is_never_written_again(tmp_path: Path) -> None:
    store = store_with_a_raw_file(tmp_path)
    record(store)
    source = tmp_path / "bars.dbn"
    source.write_bytes(RAW_BYTES)

    with pytest.raises(ValueError, match="which it records: raw files never change"):
        store.raw.write(RAW_PATH, source, JOB.published_sha256)


def test_a_recorded_raw_file_reads_back_and_a_changed_one_is_refused(tmp_path: Path) -> None:
    store = store_with_a_raw_file(tmp_path)
    recorded = record(store)

    assert store.raw.read(RAW_PATH) == RAW_BYTES
    (tmp_path / "raw" / RAW_PATH).write_bytes(b"changed")
    with pytest.raises(ValueError, match=f"recorded SHA-256 {recorded.sha256}"):
        store.raw.read(RAW_PATH)
    with pytest.raises(FileNotFoundError, match="got no such entry"):
        store.raw.read(PurePosixPath("vendor/job-1/other.dbn"))
