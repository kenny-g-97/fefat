"""The canonical market-data store on disk (ADR-0019): partitions read with Polars and written
atomically, snapshots that pin what a request read, and the raw manifest of vendor files.

`Store` takes its folder: `fefat.config.resolve_paths(os.environ).data_dir` in the app and in
notebooks, a temporary folder in tests, and the repository's `fixtures` folder for the
synthetic fixtures (provider `synthetic`). It creates nothing until it writes:

    store = Store(resolve_paths(os.environ).data_dir)
    store.list_partitions()
    es_trades = Dataset(provider="synthetic", schema_name="trades", root="ES")
    request = PartitionRequest(dataset=es_trades, start=date(2026, 3, 5), end=date(2026, 3, 9))
    snapshot = store.snapshot(request)
    store.read(snapshot)

What the files hold is `fefat.market.schema`; where they live is `fefat.market.layout`.
"""

import hashlib
import io
import shutil
from collections.abc import Callable, Iterable, Iterator
from datetime import date
from pathlib import Path, PurePosixPath

import polars as pl
from pydantic import Field

from fefat.market.layout import (
    DATASET_METADATA_FILE_NAME,
    PARTITION_FILE_NAME,
    RAW_FOLDER_NAME,
    RESERVED_FOLDERS,
    Dataset,
    DatasetMetadata,
    Partition,
    PartitionRequest,
    YearMonth,
)
from fefat.market.raw_manifest import (
    RAW_MANIFEST_FILE_NAME,
    BatchJob,
    RawFile,
    RawManifest,
    checked_raw_path,
)
from fefat.market.schema import (
    FrozenModel,
    SchemaKind,
    SchemaName,
    parse_schema_name,
    polars_schema,
    require_columns,
)
from fefat.market.snapshot import FileDigest, Snapshot
from fefat.market.store_files import (
    FileDigestRecord,
    current_digest,
    hashed,
    json_writer,
    parsed_json,
    record_digest,
    recorded_or_new_digest,
    write_atomically,
)


class PartitionFile(FrozenModel):
    """A partition the store holds, with the size of its file."""

    partition: Partition
    size_bytes: int = Field(ge=0)


class Store:
    """The canonical market-data store in one folder (ADR-0019)."""

    def __init__(self, folder: Path) -> None:
        self._folder = folder

    def __repr__(self) -> str:
        return f"Store({str(self._folder)!r})"

    @property
    def folder(self) -> Path:
        """The store's folder, `FEFAT_DATA_DIR` in the app, where the instruments an import
        saved lie beside the data (`fefat.market.saved_instruments`)."""
        return self._folder

    def list_partitions(self, dataset: Dataset | None = None) -> tuple[PartitionFile, ...]:
        """Every partition in the store, or only `dataset`'s, with the size of its file, sorted
        by path; empty while the folder does not exist."""
        if dataset is not None:
            return _sorted_by_path(self._partition_files(self._folder / dataset.relative_folder()))
        return _sorted_by_path(
            file for provider in self._providers() for file in self._partition_files(provider)
        )

    def list_datasets(self) -> tuple[Dataset, ...]:
        """Every dataset in the store, found by its `dataset.json` without listing its
        partitions, sorted by folder."""
        found = (
            Dataset(
                provider=provider.name,
                schema_name=parse_schema_name(metadata.parent.parent.name),
                root=metadata.parent.name.removeprefix("root="),
            )
            for provider in self._providers()
            for metadata in provider.glob(f"*/root=*/{DATASET_METADATA_FILE_NAME}")
        )
        return tuple(sorted(found, key=lambda dataset: dataset.relative_folder().as_posix()))

    def scan(self, request: PartitionRequest) -> pl.LazyFrame:
        """The rows of the request's dataset on its trade dates, read lazily: trades and TBBO
        by their partitions, bars by their `trade_date`. Definitions, statistics, and funding
        carry no trade date and come whole, for the reader to cut at `ts_recv`. Rows come file
        by file in path order (contract, then date): sort them before relying on time order.
        A run reads through `snapshot` and `read` instead."""
        return self.scan_contracts(request).drop("contract")

    def scan_contracts(self, request: PartitionRequest) -> pl.LazyFrame:
        """`scan`'s rows with the `contract` of the partition each comes from as a last column,
        since records name their instrument but not their contract (the roll calendar of
        `fefat.market.continuous` reads them)."""
        rows = pl.concat(
            [
                self.scan_partition(file.partition).with_columns(
                    contract=pl.lit(file.partition.contract)
                )
                for file in self._selected(request)
            ]
        )
        return rows.filter(_within_the_dates(request))

    def has_partition(self, partition: Partition) -> bool:
        """Whether the store holds the partition's file."""
        return (self._folder / partition.relative_path()).is_file()

    def scan_partition(self, partition: Partition) -> pl.LazyFrame:
        """One partition's rows, read lazily, once its file's columns match its schema."""
        path = self._folder / partition.relative_path()
        rows = pl.scan_parquet(path, hive_partitioning=False)
        expected = polars_schema(partition.dataset.schema_name)
        require_columns(expected, rows.collect_schema(), str(path))
        return rows

    def write_partition(self, partition: Partition, frame: pl.DataFrame) -> PartitionFile:
        """Write a partition, replacing any earlier file of it in one step. The frame's columns
        must match the schema, bars must fall on the partition's trade date or month, and the
        dataset needs its metadata first."""
        source = f"the frame for {partition.relative_path()}"
        require_columns(polars_schema(partition.dataset.schema_name), frame.schema, source)
        _require_trade_dates_of_the_key(partition, frame)
        self.dataset_metadata(partition.dataset)
        path = self._folder / partition.relative_path()
        write_atomically(path, lambda temporary: frame.write_parquet(temporary, compression="zstd"))
        return PartitionFile(partition=partition, size_bytes=record_digest(path).size_bytes)

    def has_dataset_metadata(self, dataset: Dataset) -> bool:
        """Whether the store holds the dataset's `dataset.json`."""
        return (self._folder / dataset.metadata_path()).is_file()

    def dataset_metadata(self, dataset: Dataset) -> DatasetMetadata:
        """The dataset's metadata, from its `dataset.json`."""
        path = self._folder / dataset.metadata_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"Expected the metadata of {dataset.relative_folder()} in {path}, got no such "
                "file; write it with write_dataset_metadata before the dataset's partitions."
            )
        return parsed_json(DatasetMetadata, path.read_bytes(), str(path))

    def write_dataset_metadata(self, dataset: Dataset, metadata: DatasetMetadata) -> None:
        """Write the dataset's `dataset.json`, replacing any earlier one in one step."""
        write_atomically(self._folder / dataset.metadata_path(), json_writer(metadata))

    def snapshot(self, request: PartitionRequest) -> Snapshot:
        """Pin the dataset's metadata and the partitions the request selects by their content,
        taking a partition's digest from beside its file while it describes the file
        (`fefat.market.store_files`), hashing the file otherwise, and writing nothing; metadata
        that does not parse is refused, so a run never pins a size unit it cannot read."""
        return self._snapshot(request, current_digest)

    def record_digests(self, request: PartitionRequest) -> Snapshot:
        """`snapshot`, recording beside each partition the digest it had to compute, so that
        later snapshots read none of these files."""
        return self._snapshot(request, recorded_or_new_digest)

    def read(self, snapshot: Snapshot) -> pl.DataFrame:
        """The rows a snapshot pinned, cut to its request's dates like `scan`, parsed from
        bytes whose SHA-256 matches the pin, so that a run reads exactly the data it names; a
        file that changed after the snapshot is refused."""
        self.pinned_metadata(snapshot)
        expected = polars_schema(snapshot.request.dataset.schema_name)
        frames = [self._pinned_partition(digest, expected) for digest in snapshot.partitions]
        return pl.concat(frames).filter(_within_the_dates(snapshot.request))

    def read_pinned_partition(self, snapshot: Snapshot, digest: FileDigest) -> pl.DataFrame:
        """One partition the snapshot pinned, cut to its request's dates as `read` cuts them
        and parsed from bytes whose SHA-256 matches the pin, so that a reader of many partitions,
        such as the engine cache's builder, holds one at a time."""
        if digest not in snapshot.partitions:
            raise ValueError(
                f"Expected a partition the snapshot {snapshot.sha256} pins, got {digest.path}."
            )
        expected = polars_schema(snapshot.request.dataset.schema_name)
        partition = self._pinned_partition(digest, expected)
        return partition.filter(_within_the_dates(snapshot.request))

    def pinned_metadata(self, snapshot: Snapshot) -> DatasetMetadata:
        """The dataset's metadata as the snapshot pinned it, such as the size unit a run's
        rows count in; refused if `dataset.json` changed after the snapshot."""
        content = self._pinned_bytes(snapshot.metadata)
        return parsed_json(DatasetMetadata, content, snapshot.metadata.path)

    def raw_manifest(self) -> RawManifest:
        """The raw manifest; empty until the first raw file is recorded."""
        path = self._raw_manifest_path()
        if not path.is_file():
            return RawManifest()
        return parsed_json(RawManifest, path.read_bytes(), str(path))

    def write_raw_file(self, path: PurePosixPath, source: Path, sha256: str) -> None:
        """Copy a vendor's file to `raw/<path>` in one step, once the copy's SHA-256 is the
        one stated, replacing a copy an interrupted import left behind. A path the raw manifest
        records is refused, since raw files never change; record the copy with
        `record_raw_file` once it is imported."""
        relative = checked_raw_path(path.as_posix())
        if self.raw_manifest().file_at(relative) is not None:
            raise ValueError(
                f"Expected a raw file the manifest {self._raw_manifest_path()} does not record, "
                f"got {relative}, which it records: raw files never change."
            )
        write_atomically(self._folder / RAW_FOLDER_NAME / relative, _verified_copy(source, sha256))

    def raw_file(self, path: PurePosixPath) -> bytes:
        """The bytes of a raw file the manifest records, refused when they no longer match its
        recorded SHA-256."""
        relative = checked_raw_path(path.as_posix())
        recorded = self.raw_manifest().file_at(relative)
        if recorded is None:
            raise FileNotFoundError(
                f"Expected {relative} in the raw manifest {self._raw_manifest_path()}, got no "
                "such entry."
            )
        content = self._vendor_file(relative).read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        if actual != recorded.sha256:
            raise ValueError(
                f"Expected the raw file {relative} with its recorded SHA-256 {recorded.sha256}, "
                f"got {actual}: raw files never change."
            )
        return content

    def record_raw_file(
        self,
        path: PurePosixPath,
        provider: str,
        vendor_version: str,
        downloaded_on: date,
        batch_job: BatchJob | None,
        imported_on: date,
        roots: tuple[str, ...],
    ) -> RawFile:
        """Record a vendor's file under `raw` in the raw manifest, with its size and SHA-256,
        the day it was imported, and the roots its records fed.

        Recording the same file again changes nothing. Raw files are immutable, so a recorded
        file whose bytes or details changed is refused: a vendor's re-normalised history
        arrives as a new file."""
        relative = checked_raw_path(path.as_posix())
        digest = hashed(self._vendor_file(relative))
        raw_file = RawFile(
            path=relative,
            size_bytes=digest.size_bytes,
            sha256=digest.sha256,
            provider=provider,
            vendor_version=vendor_version,
            downloaded_on=downloaded_on,
            batch_job=batch_job,
            imported_on=imported_on,
            roots=roots,
        )
        manifest = self.raw_manifest()
        recorded = manifest.file_at(relative)
        if recorded is None:
            write_atomically(self._raw_manifest_path(), json_writer(manifest.with_file(raw_file)))
            return raw_file
        if recorded != raw_file:
            raise ValueError(
                f"Expected the raw file {relative} as {self._raw_manifest_path()} records it, "
                f"since raw files are immutable: recorded {recorded.model_dump_json()}, got "
                f"{raw_file.model_dump_json()}."
            )
        return recorded

    def _vendor_file(self, relative: str) -> Path:
        """The vendor's file under `raw`, refused when it is missing or when it is the manifest
        under another name, such as a hard link or a short 8.3 name."""
        file = self._folder / RAW_FOLDER_NAME / relative
        if not file.is_file():
            raise FileNotFoundError(f"Expected the raw file {file}, got no such file.")
        manifest = self._raw_manifest_path()
        if manifest.is_file() and file.samefile(manifest):
            raise ValueError(
                f"Expected a vendor's file inside the raw folder, got {relative!r}, another name "
                "of the raw manifest."
            )
        return file

    def _providers(self) -> Iterator[Path]:
        """The providers' folders: every folder of the store but `raw` and `reports`."""
        if not self._folder.is_dir():
            return
        for folder in self._folder.iterdir():
            if folder.is_dir() and folder.name.lower() not in RESERVED_FOLDERS:
                yield folder

    def _partition_files(self, folder: Path) -> Iterator[PartitionFile]:
        for path in folder.rglob(PARTITION_FILE_NAME):
            relative = PurePosixPath(path.relative_to(self._folder).as_posix())
            yield PartitionFile(
                partition=Partition.from_relative_path(relative), size_bytes=path.stat().st_size
            )

    def _selected(self, request: PartitionRequest) -> tuple[PartitionFile, ...]:
        dataset_folder = self._folder / request.dataset.relative_folder()
        selected = _sorted_by_path(
            file
            for file in self._partition_files(dataset_folder)
            if request.selects(file.partition)
        )
        if not selected:
            raise ValueError(
                f"Expected at least one partition of {request.dataset.relative_folder()} from "
                f"{request.start} to {request.end}, got none in {self._folder}."
            )
        return selected

    def _snapshot(
        self, request: PartitionRequest, digest_of: Callable[[Path], FileDigestRecord]
    ) -> Snapshot:
        self.dataset_metadata(request.dataset)
        partitions = tuple(
            self._pin(file.partition.relative_path(), digest_of) for file in self._selected(request)
        )
        return Snapshot.of(request, self._pin(request.dataset.metadata_path(), hashed), partitions)

    def _pin(
        self, relative: PurePosixPath, digest_of: Callable[[Path], FileDigestRecord]
    ) -> FileDigest:
        path = self._folder / relative
        if not path.is_file():
            raise FileNotFoundError(f"Expected the file {path} to pin, got no such file.")
        digest = digest_of(path)
        return FileDigest(
            path=relative.as_posix(), size_bytes=digest.size_bytes, sha256=digest.sha256
        )

    def _pinned_bytes(self, digest: FileDigest) -> bytes:
        content = (self._folder / digest.path).read_bytes()
        actual = hashlib.sha256(content).hexdigest()
        if actual != digest.sha256:
            raise ValueError(
                f"Expected the SHA-256 {digest.sha256} that pinned {digest.path}, got {actual}: "
                "the file changed after the snapshot."
            )
        return content

    def _pinned_partition(self, digest: FileDigest, expected: pl.Schema) -> pl.DataFrame:
        frame = pl.read_parquet(io.BytesIO(self._pinned_bytes(digest)))
        require_columns(expected, frame.schema, digest.path)
        return frame

    def _raw_manifest_path(self) -> Path:
        return self._folder / RAW_FOLDER_NAME / RAW_MANIFEST_FILE_NAME


def _sorted_by_path(files: Iterable[PartitionFile]) -> tuple[PartitionFile, ...]:
    return tuple(sorted(files, key=lambda file: file.partition.relative_path().as_posix()))


def _within_the_dates(request: PartitionRequest) -> pl.Expr:
    """Bars carry their trade date, so a range keeps only its own bars; other records come
    whole (trades and TBBO are already cut by their trade-date partitions)."""
    if not _carries_trade_dates(request.dataset.schema_name):
        return pl.lit(True)
    return pl.col("trade_date").is_between(request.start, request.end)


def _carries_trade_dates(schema_name: SchemaName) -> bool:
    """Bars carry their session's trade date; ticks get theirs from their partition, and the
    other records have none."""
    return schema_name.kind is SchemaKind.OHLCV


def _require_trade_dates_of_the_key(partition: Partition, frame: pl.DataFrame) -> None:
    """Reads select bars by their partition's key and keep them by their trade date, so a bar
    without a trade date, or with one outside its partition's date or month, is refused."""
    if not _carries_trade_dates(partition.dataset.schema_name):
        return
    trade_date = pl.col("trade_date")
    inside = pl.lit(True)
    if isinstance(partition.key, YearMonth):
        month = partition.key
        inside = (trade_date.dt.year() == month.year) & (trade_date.dt.month() == month.month)
    elif partition.key is not None:
        inside = trade_date == partition.key
    strays = frame.filter(inside.not_() | trade_date.is_null()).get_column("trade_date")
    if not strays.is_empty():
        raise ValueError(
            f"Expected every bar of {partition.relative_path()} with a trade date of its key "
            f"{partition.key}, got the trade dates {strays.unique().sort().to_list()[:5]}."
        )


def _verified_copy(source: Path, sha256: str) -> Callable[[Path], object]:
    def copy(temporary: Path) -> None:
        shutil.copyfile(source, temporary)
        copied = hashed(temporary).sha256
        if copied != sha256:
            raise ValueError(
                f"Expected the copy of {source} to have the SHA-256 {sha256}, got {copied}."
            )

    return copy
