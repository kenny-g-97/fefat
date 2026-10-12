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
import os
import tempfile
from collections.abc import Callable, Iterable, Iterator
from datetime import date
from pathlib import Path, PurePosixPath

import polars as pl
from pydantic import BaseModel, Field, ValidationError

from fefat.market.layout import (
    PARTITION_FILE_NAME,
    RAW_FOLDER_NAME,
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
from fefat.market.schema import FrozenModel, SchemaKind, SchemaName, polars_schema
from fefat.market.snapshot import FileDigest, Snapshot


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

    def list_partitions(self) -> tuple[PartitionFile, ...]:
        """Every partition in the store with the size of its file, sorted by path; empty while
        the folder does not exist."""
        if not self._folder.is_dir():
            return ()
        providers = (
            folder
            for folder in self._folder.iterdir()
            if folder.is_dir() and folder.name.lower() != RAW_FOLDER_NAME
        )
        return _sorted_by_path(
            file for provider in providers for file in self._partition_files(provider)
        )

    def scan(self, request: PartitionRequest) -> pl.LazyFrame:
        """The rows of the request's dataset on its trade dates, read lazily: trades and TBBO
        by their partitions, bars by their `trade_date`. Definitions, statistics, and funding
        carry no trade date and come whole, for the reader to cut at `ts_recv`. Rows come file
        by file in path order (contract, then date): sort them before relying on time order.
        A run reads through `snapshot` and `read` instead."""
        rows = pl.concat([self.scan_partition(file.partition) for file in self._selected(request)])
        return rows.filter(_within_the_dates(request))

    def scan_partition(self, partition: Partition) -> pl.LazyFrame:
        """One partition's rows, read lazily, once its file's columns match its schema."""
        path = self._folder / partition.relative_path()
        rows = pl.scan_parquet(path, hive_partitioning=False)
        expected = polars_schema(partition.dataset.schema_name)
        _require_columns(expected, rows.collect_schema(), str(path))
        return rows

    def write_partition(self, partition: Partition, frame: pl.DataFrame) -> PartitionFile:
        """Write a partition, replacing any earlier file of it in one step. The frame's columns
        must match the schema, bars must fall on the partition's trade date or month, and the
        dataset needs its metadata first."""
        source = f"the frame for {partition.relative_path()}"
        _require_columns(polars_schema(partition.dataset.schema_name), frame.schema, source)
        _require_trade_dates_of_the_key(partition, frame)
        self.dataset_metadata(partition.dataset)
        path = self._folder / partition.relative_path()
        _write_atomically(
            path, lambda temporary: frame.write_parquet(temporary, compression="zstd")
        )
        return PartitionFile(partition=partition, size_bytes=path.stat().st_size)

    def dataset_metadata(self, dataset: Dataset) -> DatasetMetadata:
        """The dataset's metadata, from its `dataset.json`."""
        path = self._folder / dataset.metadata_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"Expected the metadata of {dataset.relative_folder()} in {path}, got no such "
                "file; write it with write_dataset_metadata before the dataset's partitions."
            )
        return _parsed_json(DatasetMetadata, path)

    def write_dataset_metadata(self, dataset: Dataset, metadata: DatasetMetadata) -> None:
        """Write the dataset's `dataset.json`, replacing any earlier one in one step."""
        _write_atomically(self._folder / dataset.metadata_path(), _json_writer(metadata))

    def snapshot(self, request: PartitionRequest) -> Snapshot:
        """Pin the dataset's metadata and the partitions the request selects by their content."""
        partitions = tuple(
            self._digest(file.partition.relative_path()) for file in self._selected(request)
        )
        return Snapshot.of(request, self._digest(request.dataset.metadata_path()), partitions)

    def read(self, snapshot: Snapshot) -> pl.DataFrame:
        """The rows a snapshot pinned, cut to its request's dates like `scan`, parsed from
        bytes whose SHA-256 matches the pin, so that a run reads exactly the data it names; a
        file that changed after the snapshot is refused."""
        self.pinned_metadata(snapshot)
        expected = polars_schema(snapshot.request.dataset.schema_name)
        frames = [self._pinned_partition(digest, expected) for digest in snapshot.partitions]
        return pl.concat(frames).filter(_within_the_dates(snapshot.request))

    def pinned_metadata(self, snapshot: Snapshot) -> DatasetMetadata:
        """The dataset's metadata as the snapshot pinned it, such as the size unit a run's
        rows count in; refused if `dataset.json` changed after the snapshot."""
        return DatasetMetadata.model_validate_json(self._pinned_bytes(snapshot.metadata))

    def raw_manifest(self) -> RawManifest:
        """The raw manifest; empty until the first raw file is recorded."""
        path = self._raw_manifest_path()
        if not path.is_file():
            return RawManifest()
        return _parsed_json(RawManifest, path)

    def record_raw_file(
        self,
        path: PurePosixPath,
        provider: str,
        vendor_version: str,
        downloaded_on: date,
        batch_job: BatchJob | None,
    ) -> RawFile:
        """Record a vendor's file under `raw` in the raw manifest, with its size and SHA-256.

        Recording the same file again changes nothing. Raw files are immutable, so a recorded
        file whose bytes or details changed is refused: a vendor's re-normalised history
        arrives as a new file."""
        relative = checked_raw_path(path.as_posix())
        file = self._folder / RAW_FOLDER_NAME / relative
        if not file.is_file():
            raise FileNotFoundError(f"Expected the raw file {file}, got no such file.")
        size_bytes, sha256 = _size_and_sha256(file)
        raw_file = RawFile(
            path=relative,
            size_bytes=size_bytes,
            sha256=sha256,
            provider=provider,
            vendor_version=vendor_version,
            downloaded_on=downloaded_on,
            batch_job=batch_job,
        )
        manifest = self.raw_manifest()
        recorded = manifest.file_at(relative)
        if recorded is None:
            _write_atomically(self._raw_manifest_path(), _json_writer(manifest.with_file(raw_file)))
            return raw_file
        if recorded != raw_file:
            raise ValueError(
                f"Expected the raw file {relative} as {self._raw_manifest_path()} records it, "
                f"since raw files are immutable: recorded {recorded.model_dump_json()}, got "
                f"{raw_file.model_dump_json()}."
            )
        return recorded

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

    def _digest(self, relative: PurePosixPath) -> FileDigest:
        path = self._folder / relative
        if not path.is_file():
            raise FileNotFoundError(f"Expected the file {path} to pin, got no such file.")
        size_bytes, sha256 = _size_and_sha256(path)
        return FileDigest(path=relative.as_posix(), size_bytes=size_bytes, sha256=sha256)

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
        _require_columns(expected, frame.schema, digest.path)
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


def _require_columns(expected: pl.Schema, actual: pl.Schema, source: str) -> None:
    if actual != expected:
        raise ValueError(
            f"Expected the columns {_described(expected)}, got {_described(actual)} in {source}."
        )


def _described(columns: pl.Schema) -> str:
    return ", ".join(f"{name} {dtype}" for name, dtype in columns.items())


def _require_trade_dates_of_the_key(partition: Partition, frame: pl.DataFrame) -> None:
    """A request selects bars by their partition's key, so a bar written under another trade
    date or month would be read for the wrong dates; it is refused."""
    if partition.key is None or not _carries_trade_dates(partition.dataset.schema_name):
        return
    trade_date = pl.col("trade_date")
    if isinstance(partition.key, YearMonth):
        month = partition.key
        inside = (trade_date.dt.year() == month.year) & (trade_date.dt.month() == month.month)
    else:
        inside = trade_date == partition.key
    strays = frame.filter(inside.not_() | trade_date.is_null()).get_column("trade_date")
    if not strays.is_empty():
        raise ValueError(
            f"Expected every bar of {partition.relative_path()} on its key {partition.key}, "
            f"got the trade dates {strays.unique().sort().to_list()[:5]}."
        )


def _parsed_json[Model: BaseModel](model: type[Model], path: Path) -> Model:
    try:
        return model.model_validate_json(path.read_bytes())
    except ValidationError as error:
        raise ValueError(f"Expected {path} to hold a {model.__name__}, got: {error}") from error


def _json_writer(model: BaseModel) -> Callable[[Path], object]:
    content = model.model_dump_json(indent=2).encode() + b"\n"
    return lambda temporary: temporary.write_bytes(content)


def _write_atomically(path: Path, write: Callable[[Path], object]) -> None:
    """Write through a temporary file beside the target, flush it to disk, then replace the
    target in one step (atomic on one NTFS or POSIX volume): a reader, or a power cut, sees
    the old file or the new one, never half of one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.stem}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        write(temporary)
        with temporary.open("rb+") as written:
            os.fsync(written.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _size_and_sha256(path: Path) -> tuple[int, str]:
    """The file's size and SHA-256, both from one open handle, so they describe one file."""
    with path.open("rb") as file:
        size_bytes = os.fstat(file.fileno()).st_size
        return size_bytes, hashlib.file_digest(file, "sha256").hexdigest()
