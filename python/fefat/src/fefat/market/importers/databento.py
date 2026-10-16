"""Importing Databento's files (`02-engine-and-data.md` §1.8, D-38): a batch download, which is
the DBN files beside the vendor's `metadata.json`, `manifest.json`, and `condition.json`, or a
single DBN file (`.dbn`, `.dbn.zst`). No network and no key: a purchase is made and downloaded on
the vendor's website, and its files come through here.

`import_databento` checks every file it is about to read against the SHA-256 the batch's
`manifest.json` publishes, refusing a mismatch with both hashes, before it writes anything; a
batch split into several DBN files is refused, since its files can share partitions, which are
not merged yet. It writes the records as canonical partitions (`file_writer`), each dataset's
`dataset.json` naming its origin, an import, and the licence scope of Databento's entry in the
source guide (`fefat.market.sources`), then keeps the file unchanged under
`raw/databento/<job>/` (a single file under `raw/databento/<its SHA-256>/`, since the vendor
names files by dates and schema, not by product) with its entry in the raw manifest, recorded
last: the job id and the published SHA-256, the DBN version and the newest revision date in
`condition.json` (`DBN 3, revised 2026-09-23`), the download date the job id carries, or, for
a single file, the UTC date it was last written, the day of the import, and the roots whose
records the file held (none for the sidecars). So an interrupted import runs again, a refused
one leaves no copy behind, and a finished one imports nothing twice and reads none of its
files again.
A file the raw manifest records with other bytes is refused: raw files never change, so a
corrected download arrives as a new file. The vendor's daily bars (`ohlcv-1d`) are cut on UTC
days rather than sessions and are skipped (ADR-0019). `vendor_conditions` reads a batch's
per-day conditions back for the quality report (1.8).

    paths = resolve_paths(os.environ)
    today = datetime.now(UTC).date()
    report = import_databento(
        Path("market_data/MNQ"), Store(paths.data_dir), paths.cache_dir, imported_on=today
    )
    print(report.summary())
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from fefat.market.importers.canonical import RecordPlacement, active_days
from fefat.market.importers.dbn import read_dbn
from fefat.market.importers.file_writer import write_records
from fefat.market.importers.partition_buffers import CONTRACT_SIZE
from fefat.market.importers.report import (
    BatchReport,
    ConditionDay,
    DatabentoImport,
    FileImport,
    VendorCondition,
)
from fefat.market.instruments import STATIC_TABLE, InstrumentTable
from fefat.market.layout import DatasetMetadata, DatasetOrigin
from fefat.market.raw_manifest import BatchJob
from fefat.market.schema import parse_schema_name
from fefat.market.sources import SOURCE_GUIDE
from fefat.market.store import Store

PROVIDER = "databento"
"""The provider folder of Databento's datasets and raw files."""

_VENDOR_MANIFEST = "manifest.json"
_QUERY = "metadata.json"
_CONDITIONS = "condition.json"
_DBN_SUFFIXES = (".dbn", ".dbn.zst")
_JOB_ID = re.compile(r"[A-Z0-9.]+-([0-9]{4})([0-9]{2})([0-9]{2})-[A-Z0-9]+")
_DAILY_BARS = parse_schema_name("ohlcv-1d")


class VendorModel(BaseModel):
    """A value read from a vendor's file, which may carry fields the importer does not read."""

    model_config = ConfigDict(frozen=True, extra="ignore")


class BatchFile(VendorModel):
    """A file of a batch download as `manifest.json` lists it, with its published SHA-256."""

    filename: str = Field(min_length=1)
    hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    def published_sha256(self) -> str:
        return self.hash.removeprefix("sha256:")


class BatchManifest(VendorModel):
    """A batch download's `manifest.json`: its job and every other file in it."""

    job_id: str = Field(min_length=1)
    files: tuple[BatchFile, ...] = Field(min_length=1)


class BatchQuery(VendorModel):
    """A batch download's `metadata.json`, the query it answers; the importer reads its job."""

    job_id: str = Field(min_length=1)


class DayCondition(VendorModel):
    """A day of `condition.json`: how complete the vendor says its data is, and when the vendor
    last changed it."""

    day: date = Field(alias="date")
    condition: VendorCondition
    last_modified_date: date | None = None


_CONDITION_DAYS = TypeAdapter(tuple[DayCondition, ...])


@dataclass(frozen=True)
class _Original:
    """A vendor's file to keep under `raw`: where it is, where it goes, its SHA-256, and the
    batch job it came in."""

    source: Path
    raw_path: PurePosixPath
    sha256: str
    batch_job: BatchJob | None


@dataclass(frozen=True)
class _Batch:
    """A batch download as its vendor's files describe it: one DBN file and its sidecars."""

    folder: Path
    job_id: str
    downloaded_on: date
    conditions: tuple[DayCondition, ...]
    sidecars: tuple[_Original, ...]
    data_file: _Original

    def revised(self) -> date | None:
        """The newest day the vendor changed any of the batch's days, if it gives one."""
        dates = [day.last_modified_date for day in self.conditions if day.last_modified_date]
        return max(dates, default=None)

    def revision(self) -> str:
        """The batch's revision as the raw manifest records it."""
        revised = self.revised()
        return "no revision date" if revised is None else f"revised {revised}"

    def report(self) -> BatchReport:
        unavailable = tuple(
            ConditionDay(day=day.day, condition=day.condition)
            for day in self.conditions
            if day.condition is not VendorCondition.AVAILABLE
        )
        return BatchReport(job_id=self.job_id, revised=self.revised(), unavailable_days=unavailable)


class _DataFileImporter:
    """Imports DBN data files into one store, dating their records by the calendars in the
    cache folder and naming their contracts within the instrument table."""

    def __init__(
        self, store: Store, cache_folder: Path, instruments: InstrumentTable, imported_on: date
    ) -> None:
        self._store = store
        self._cache_folder = cache_folder
        self._instruments = instruments
        self.imported_on = imported_on
        self._metadata = DatasetMetadata(
            size_unit=CONTRACT_SIZE,
            origin=DatasetOrigin.IMPORT,
            licence_scope=SOURCE_GUIDE.source_of_preset(PROVIDER).licence_scope,
        )

    def imported(
        self, original: _Original, revision: str, downloaded_on: date
    ) -> FileImport | None:
        """The file's records written, then the file kept under `raw` and recorded last;
        `None` for the vendor's daily bars, which are skipped. The file is read twice,
        streaming: once for the days each instrument has records, which name its contracts,
        then to write."""
        metadata, frames = read_dbn(original.source)
        if metadata.schema_name == _DAILY_BARS:
            return None
        days = active_days(frames, metadata.schema_name)
        placement = RecordPlacement(
            original.source, metadata, days, PROVIDER, self._instruments, self._cache_folder
        )
        _, frames = read_dbn(original.source)
        report = write_records(
            frames, placement, self._store, original.raw_path.as_posix(), self._metadata
        )
        self._store.write_raw_file(original.raw_path, original.source, original.sha256)
        self._store.record_raw_file(
            original.raw_path,
            provider=PROVIDER,
            vendor_version=f"DBN {metadata.version}{revision}",
            downloaded_on=downloaded_on,
            batch_job=original.batch_job,
            imported_on=self.imported_on,
            roots=tuple(sorted({contract.root for contract in report.contracts})),
        )
        return report


def import_databento(
    source: Path,
    store: Store,
    cache_folder: Path,
    *,
    imported_on: date,
    instruments: InstrumentTable = STATIC_TABLE,
) -> DatabentoImport:
    """Import a Databento batch-download folder or a single DBN file into `store`, with the
    session tables built in `cache_folder`, recording `imported_on` as the day its files were
    imported, and report what was imported."""
    importer = _DataFileImporter(store, cache_folder, instruments, imported_on)
    if source.is_dir():
        return _import_batch(_batch(source), store, importer)
    if source.is_file():
        return _import_file(source, store, importer)
    raise FileNotFoundError(
        f"Expected a Databento batch folder or DBN file, got no such path: {source}."
    )


def vendor_conditions(store: Store, job_id: str) -> pl.DataFrame:
    """The per-day conditions of a batch download the store keeps, from its `condition.json`:
    `date`, `condition` (available, degraded, pending, or missing), and the vendor's
    `last_modified_date`, sorted by date."""
    content = store.raw_file(PurePosixPath(PROVIDER, job_id, _CONDITIONS))
    days = _CONDITION_DAYS.validate_json(content)
    return pl.DataFrame(
        {
            "date": [day.day for day in days],
            "condition": [str(day.condition) for day in days],
            "last_modified_date": [day.last_modified_date for day in days],
        },
        schema={"date": pl.Date, "condition": pl.String, "last_modified_date": pl.Date},
    ).sort("date")


def _import_batch(batch: _Batch, store: Store, importer: _DataFileImporter) -> DatabentoImport:
    _refuse_changed_originals(store, (*batch.sidecars, batch.data_file))
    unrecorded = [
        original
        for original in (*batch.sidecars, batch.data_file)
        if not _recorded(store, original)
    ]
    for original in unrecorded:
        _require_published(original, batch.folder)
    for sidecar in batch.sidecars:
        if sidecar in unrecorded:
            store.write_raw_file(sidecar.raw_path, sidecar.source, sidecar.sha256)
            store.record_raw_file(
                sidecar.raw_path,
                provider=PROVIDER,
                vendor_version=batch.revision(),
                downloaded_on=batch.downloaded_on,
                batch_job=sidecar.batch_job,
                imported_on=importer.imported_on,
                roots=(),
            )
    raw_path = batch.data_file.raw_path.as_posix()
    report = None
    if batch.data_file in unrecorded:
        report = importer.imported(batch.data_file, f", {batch.revision()}", batch.downloaded_on)
    return DatabentoImport(
        source=str(batch.folder),
        batch=batch.report(),
        files=() if report is None else (report,),
        already_imported=() if batch.data_file in unrecorded else (raw_path,),
        daily_bars_skipped=(raw_path,) if batch.data_file in unrecorded and report is None else (),
    )


def _import_file(path: Path, store: Store, importer: _DataFileImporter) -> DatabentoImport:
    if not path.name.endswith(_DBN_SUFFIXES):
        raise ValueError(
            f"Expected a DBN file ({', '.join(_DBN_SUFFIXES)}) or a batch folder, got {path}: "
            "other exports arrive through `fefat data import file` (step 1.10)."
        )
    sha256 = _sha256(path)
    original = _Original(path, PurePosixPath(PROVIDER, sha256, path.name), sha256, None)
    raw_path = original.raw_path.as_posix()
    if _recorded(store, original):
        return DatabentoImport(
            source=str(path),
            batch=None,
            files=(),
            already_imported=(raw_path,),
            daily_bars_skipped=(),
        )
    downloaded_on = datetime.fromtimestamp(path.stat().st_mtime, UTC).date()
    report = importer.imported(original, "", downloaded_on)
    return DatabentoImport(
        source=str(path),
        batch=None,
        files=() if report is None else (report,),
        already_imported=(),
        daily_bars_skipped=(raw_path,) if report is None else (),
    )


def _batch(folder: Path) -> _Batch:
    """The batch download in `folder`, as its sidecars describe it; its files are checked
    against the vendor's hashes only when they are about to be read."""
    manifest = _parsed(BatchManifest, folder / _VENDOR_MANIFEST)
    query = _parsed(BatchQuery, folder / _QUERY)
    if query.job_id != manifest.job_id:
        raise ValueError(
            f"Expected the job of {folder / _VENDOR_MANIFEST}, {manifest.job_id}, in "
            f"{folder / _QUERY}, got {query.job_id}."
        )
    listed = {file.filename: file for file in manifest.files}
    data_name = _data_file_name(folder, listed)
    job = manifest.job_id

    def original(name: str) -> _Original:
        published = listed[name].published_sha256()
        batch_job = BatchJob(job_id=job, published_sha256=published)
        return _Original(folder / name, PurePosixPath(PROVIDER, job, name), published, batch_job)

    vendor_manifest = folder / _VENDOR_MANIFEST
    return _Batch(
        folder=folder,
        job_id=job,
        downloaded_on=_job_date(job),
        conditions=_condition_days(folder / _CONDITIONS),
        sidecars=(
            original(_QUERY),
            original(_CONDITIONS),
            _Original(
                vendor_manifest,
                PurePosixPath(PROVIDER, job, _VENDOR_MANIFEST),
                _sha256(vendor_manifest),
                None,
            ),
        ),
        data_file=original(data_name),
    )


def _data_file_name(folder: Path, listed: dict[str, BatchFile]) -> str:
    """The batch's DBN file, once its manifest lists the query, the conditions, one DBN file,
    and nothing else."""
    data_names = sorted(name for name in listed if name.endswith(_DBN_SUFFIXES))
    others = sorted(set(listed) - {_QUERY, _CONDITIONS, *data_names})
    if not {_QUERY, _CONDITIONS} <= set(listed) or not data_names or others:
        raise ValueError(
            f"Expected {folder / _VENDOR_MANIFEST} to list {_QUERY}, {_CONDITIONS}, and DBN "
            f"files, got {', '.join(sorted(listed))}: a batch encoded in CSV or JSON arrives "
            "through `fefat data import file` (step 1.10)."
        )
    if len(data_names) > 1:
        raise ValueError(
            f"Expected one DBN file in the batch {folder}, got {len(data_names)}: "
            f"{', '.join(data_names)}. A batch split by day, month, or symbol can give two files "
            "rows of one partition, which the importer does not merge yet."
        )
    return data_names[0]


def _require_published(original: _Original, folder: Path) -> None:
    path = original.source
    if not path.is_file():
        raise FileNotFoundError(
            f"Expected {path}, which {folder / _VENDOR_MANIFEST} lists, got no such file."
        )
    actual = _sha256(path)
    if actual != original.sha256:
        raise ValueError(
            f"Expected {path} to have the SHA-256 {original.sha256} that "
            f"{folder / _VENDOR_MANIFEST} publishes, got {actual}: the file differs from the "
            "vendor's; download it again."
        )


def _refuse_changed_originals(store: Store, originals: tuple[_Original, ...]) -> None:
    """Refuse, before anything is written, files the raw manifest records with other bytes."""
    manifest = store.raw_manifest()
    changed = [
        f"{original.raw_path} recorded with the SHA-256 {recorded.sha256}, got {original.sha256}"
        for original in originals
        if (recorded := manifest.file_at(original.raw_path.as_posix())) is not None
        and recorded.sha256 != original.sha256
    ]
    if changed:
        raise ValueError(
            f"Expected the files the raw manifest records unchanged, got {'; '.join(changed)}: "
            "raw files never change, so a corrected download arrives as a new file."
        )


def _recorded(store: Store, original: _Original) -> bool:
    return store.raw_manifest().file_at(original.raw_path.as_posix()) is not None


def _job_date(job_id: str) -> date:
    """The day a batch job ran, which its id carries (`GLBX-20260923-KF6FGGLH79`)."""
    found = _JOB_ID.fullmatch(job_id)
    if found is None:
        raise ValueError(
            f"Expected a Databento job id <dataset>-<YYYYMMDD>-<code>, got {job_id!r}."
        )
    return date(int(found[1]), int(found[2]), int(found[3]))


def _condition_days(path: Path) -> tuple[DayCondition, ...]:
    if not path.is_file():
        raise FileNotFoundError(f"Expected the batch's {path}, got no such file.")
    try:
        return _CONDITION_DAYS.validate_json(path.read_bytes())
    except ValidationError as error:
        raise ValueError(f"Expected {path} to hold Databento's conditions, got: {error}") from error


def _parsed[Model: VendorModel](model: type[Model], path: Path) -> Model:
    if not path.is_file():
        raise FileNotFoundError(f"Expected the batch's {path}, got no such file.")
    try:
        return model.model_validate_json(path.read_bytes())
    except ValidationError as error:
        raise ValueError(f"Expected {path} to hold a {model.__name__}, got: {error}") from error


def _sha256(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()
