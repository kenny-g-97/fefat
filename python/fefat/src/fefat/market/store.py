"""The canonical market-data store on disk (ADR-0019): partitions read lazily with Polars,
written atomically, and pinned by snapshots, and the vendors' raw files kept in a manifest.

`Store` takes its folder: `fefat.config.resolve_paths(os.environ).data_dir` in the app and
in notebooks, a temporary folder in tests, and the repository's `fixtures` folder for the
synthetic fixtures (provider `synthetic`). It creates nothing until it writes:

    store = Store(resolve_paths(os.environ).data_dir)
    store.list_partitions()
    es_trades = Dataset(provider="synthetic", schema_name="trades", root="ES")
    request = PartitionRequest(dataset=es_trades, start=date(2026, 3, 5), end=date(2026, 3, 9))
    store.scan(request).collect()
    store.snapshot(request).sha256

What the files hold is `fefat.market.schema`; where they live is `fefat.market.layout`.
"""

import hashlib
import os
import tempfile
from collections.abc import Callable, Iterable, Iterator
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Annotated, Self

import polars as pl
from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from fefat.market.layout import (
    DATASET_METADATA_FILE_NAME,
    PARTITION_FILE_NAME,
    RAW_FOLDER_NAME,
    Dataset,
    DatasetMetadata,
    Partition,
    ProviderName,
    YearMonth,
)
from fefat.market.schema import FrozenModel, polars_schema

RAW_MANIFEST_FILE_NAME = "MANIFEST.json"

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A SHA-256 digest as 64 lowercase hex digits, without a prefix such as `sha256:`."""


class PartitionFile(FrozenModel):
    """A partition the store holds, with the size of its file."""

    partition: Partition
    size_bytes: int = Field(ge=0)


class PartitionRequest(FrozenModel):
    """The partitions of one dataset whose keys touch a range of trade dates, both ends included:
    a trade-date key inside the range, a month key with any day in it, and a partition without a
    key (one file per contract) always."""

    dataset: Dataset
    start: date
    end: date

    @model_validator(mode="after")
    def _starts_on_or_before_its_end(self) -> Self:
        if self.end < self.start:
            raise ValueError(
                f"Expected the start {self.start} on or before the end, got the end {self.end}."
            )
        return self

    def selects(self, partition: Partition) -> bool:
        """Whether the partition belongs to the dataset and its key touches the dates."""
        if partition.dataset != self.dataset:
            return False
        if isinstance(partition.key, YearMonth):
            return partition.key.overlaps(self.start, self.end)
        if isinstance(partition.key, date):
            return self.start <= partition.key <= self.end
        return True


class PartitionDigest(FrozenModel):
    """A partition file a snapshot pins: its path relative to the store folder, written with `/`
    on every system, its size, and its SHA-256."""

    path: str
    size_bytes: int = Field(ge=0)
    sha256: Sha256


def _listing_sha256(partitions: tuple[PartitionDigest, ...]) -> str:
    listing = "".join(f"{digest.sha256}  {digest.path}\n" for digest in partitions)
    return hashlib.sha256(listing.encode()).hexdigest()


class Snapshot(FrozenModel):
    """The partitions a request selected, each with its content hash, and one hash over all of
    them, so that a run pins exactly the data it read (ADR-0009).

    `sha256` is the SHA-256 of the partitions' `sha256sum` listing: one line `<sha256>  <path>`
    per partition, sorted by path, each ending in a newline."""

    request: PartitionRequest
    partitions: tuple[PartitionDigest, ...] = Field(min_length=1)
    sha256: Sha256

    @classmethod
    def of(cls, request: PartitionRequest, partitions: tuple[PartitionDigest, ...]) -> Self:
        """The snapshot of the partitions, with its hash computed."""
        return cls(request=request, partitions=partitions, sha256=_listing_sha256(partitions))

    @model_validator(mode="after")
    def _hash_covers_its_partitions(self) -> Self:
        paths = [digest.path for digest in self.partitions]
        if paths != sorted(set(paths)):
            raise ValueError(f"Expected the partitions sorted by path, each once, got {paths}.")
        expected = _listing_sha256(self.partitions)
        if self.sha256 != expected:
            raise ValueError(
                f"Expected the snapshot hash {expected} of its partitions, got {self.sha256}."
            )
        return self


def _inside_the_raw_folder(path: str) -> str:
    parts = PurePosixPath(path).parts
    outside = not parts or path.startswith("/") or PurePosixPath(path).as_posix() != path
    if outside or any(part == ".." or ":" in part or "\\" in part for part in parts):
        raise ValueError(
            f"Expected a path inside the raw folder, such as vendor/job/file.dbn, got {path!r}."
        )
    return path


RawPath = Annotated[str, AfterValidator(_inside_the_raw_folder)]
"""A vendor file's path relative to the `raw` folder, written with `/`."""


class BatchJob(FrozenModel):
    """The vendor's batch job a raw file came from, with the SHA-256 the vendor published for it
    (comparing it with the file's own is the importer's check)."""

    job_id: str = Field(min_length=1)
    published_sha256: Sha256


class RawFile(FrozenModel):
    """A vendor's original file under `raw`, as the raw manifest records it."""

    path: RawPath
    size_bytes: int = Field(ge=0)
    sha256: Sha256
    provider: ProviderName
    vendor_version: str = Field(min_length=1)
    downloaded_on: date
    batch_job: BatchJob | None


class RawManifest(FrozenModel):
    """Every raw file the store has recorded, sorted by path (`raw/MANIFEST.json`)."""

    files: tuple[RawFile, ...] = ()

    @model_validator(mode="after")
    def _records_each_path_once(self) -> Self:
        paths = [file.path for file in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError(f"Expected each raw file recorded once, got the paths {paths}.")
        return self

    def file_at(self, path: str) -> RawFile | None:
        """The record of the file at the path, if the manifest has one."""
        return next((file for file in self.files if file.path == path), None)

    def with_file(self, raw_file: RawFile) -> Self:
        """The manifest with one more file recorded."""
        files = sorted((*self.files, raw_file), key=lambda file: file.path)
        return type(self)(files=tuple(files))


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
        """The rows of every partition the request selects, in path order, read lazily."""
        return pl.concat([self.scan_partition(file.partition) for file in self._selected(request)])

    def scan_partition(self, partition: Partition) -> pl.LazyFrame:
        """One partition's rows, read lazily, once its file's columns match its schema."""
        path = self._folder / partition.relative_path()
        rows = pl.scan_parquet(path, hive_partitioning=False)
        expected = polars_schema(partition.dataset.schema_name)
        _require_columns(expected, rows.collect_schema(), str(path))
        return rows

    def write_partition(self, partition: Partition, frame: pl.DataFrame) -> PartitionFile:
        """Write a partition, replacing any earlier file of it in one step. The frame's columns
        must match the schema, and the dataset needs its metadata first."""
        source = f"the frame for {partition.relative_path()}"
        _require_columns(polars_schema(partition.dataset.schema_name), frame.schema, source)
        self.dataset_metadata(partition.dataset)
        path = self._folder / partition.relative_path()
        _write_atomically(
            path, lambda temporary: frame.write_parquet(temporary, compression="zstd")
        )
        return PartitionFile(partition=partition, size_bytes=path.stat().st_size)

    def dataset_metadata(self, dataset: Dataset) -> DatasetMetadata:
        """The dataset's metadata, from its `dataset.json`."""
        path = self._metadata_path(dataset)
        if not path.is_file():
            raise FileNotFoundError(
                f"Expected the metadata of {dataset.relative_folder()} in {path}, got no such "
                "file; write it with write_dataset_metadata before the dataset's partitions."
            )
        return DatasetMetadata.model_validate_json(path.read_bytes())

    def write_dataset_metadata(self, dataset: Dataset, metadata: DatasetMetadata) -> None:
        """Write the dataset's `dataset.json`, replacing any earlier one in one step."""
        _write_atomically(self._metadata_path(dataset), _json_writer(metadata))

    def snapshot(self, request: PartitionRequest) -> Snapshot:
        """Pin the partitions the request selects by their content, so a run names what it read."""
        return Snapshot.of(request, tuple(self._digest(file) for file in self._selected(request)))

    def raw_manifest(self) -> RawManifest:
        """The raw manifest; empty until the first raw file is recorded."""
        path = self._raw_manifest_path()
        if not path.is_file():
            return RawManifest()
        return RawManifest.model_validate_json(path.read_bytes())

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
        relative = _inside_the_raw_folder(path.as_posix())
        file = self._folder / RAW_FOLDER_NAME / relative
        if not file.is_file():
            raise FileNotFoundError(f"Expected the raw file {file}, got no such file.")
        raw_file = RawFile(
            path=relative,
            size_bytes=file.stat().st_size,
            sha256=_sha256(file),
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

    def _digest(self, file: PartitionFile) -> PartitionDigest:
        relative = file.partition.relative_path()
        return PartitionDigest(
            path=relative.as_posix(),
            size_bytes=file.size_bytes,
            sha256=_sha256(self._folder / relative),
        )

    def _metadata_path(self, dataset: Dataset) -> Path:
        return self._folder / dataset.relative_folder() / DATASET_METADATA_FILE_NAME

    def _raw_manifest_path(self) -> Path:
        return self._folder / RAW_FOLDER_NAME / RAW_MANIFEST_FILE_NAME


def _sorted_by_path(files: Iterable[PartitionFile]) -> tuple[PartitionFile, ...]:
    return tuple(sorted(files, key=lambda file: file.partition.relative_path().as_posix()))


def _require_columns(expected: pl.Schema, actual: pl.Schema, source: str) -> None:
    if actual != expected:
        raise ValueError(
            f"Expected the columns {_described(expected)}, got {_described(actual)} in {source}."
        )


def _described(columns: pl.Schema) -> str:
    return ", ".join(f"{name} {dtype}" for name, dtype in columns.items())


def _json_writer(model: BaseModel) -> Callable[[Path], object]:
    content = model.model_dump_json(indent=2).encode() + b"\n"
    return lambda temporary: temporary.write_bytes(content)


def _write_atomically(path: Path, write: Callable[[Path], object]) -> None:
    """Write through a temporary file beside the target, then replace the target in one step
    (atomic on one NTFS or POSIX volume), so that a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.stem}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        write(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()
