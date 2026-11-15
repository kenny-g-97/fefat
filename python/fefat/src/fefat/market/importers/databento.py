"""Importing Databento's files (`02-engine-and-data.md` §1.8, D-38): a batch download, which is
the DBN files beside the vendor's `metadata.json`, `manifest.json`, and `condition.json`, or a
single DBN file (`.dbn`, `.dbn.zst`). No network and no key: a purchase is made and downloaded on
the vendor's website, and its files come through here.

`import_databento` checks every file it is about to read against the SHA-256 the batch's
`manifest.json` publishes, refusing a mismatch with both hashes, before it writes anything; a
batch split into several DBN files is refused, since its files can share partitions, which are
not merged yet (`fefat.market.importers.databento_batch`). It writes the records as canonical
partitions (`file_writer`), each dataset's
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

from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

import polars as pl

from fefat.market.importers.canonical import RecordPlacement, active_days
from fefat.market.importers.databento_batch import (
    CONDITION_DAYS,
    CONDITIONS_FILE_NAME,
    DBN_SUFFIXES,
    PROVIDER,
    Batch,
    Original,
    batch_in,
    require_published,
    sha256_of,
)
from fefat.market.importers.dbn import read_dbn
from fefat.market.importers.file_writer import write_records
from fefat.market.importers.partition_buffers import CONTRACT_SIZE
from fefat.market.importers.report import DatabentoImport, FileImport
from fefat.market.instruments import STATIC_TABLE, InstrumentTable
from fefat.market.layout import DatasetMetadata, DatasetOrigin
from fefat.market.schema import parse_schema_name
from fefat.market.sources import SOURCE_GUIDE, SourceGuide
from fefat.market.store import Store

__all__ = ["PROVIDER", "import_databento", "vendor_conditions"]

_DAILY_BARS = parse_schema_name("ohlcv-1d")


class _DataFileImporter:
    """Imports DBN data files into one store, dating their records by the calendars in the
    cache folder and naming their contracts within the instrument table."""

    def __init__(
        self,
        store: Store,
        cache_folder: Path,
        instruments: InstrumentTable,
        imported_on: date,
        guide: SourceGuide,
    ) -> None:
        self._store = store
        self._cache_folder = cache_folder
        self._instruments = instruments
        self.imported_on = imported_on
        self._metadata = DatasetMetadata(
            size_unit=CONTRACT_SIZE,
            origin=DatasetOrigin.IMPORT,
            licence_scope=guide.source_of_preset(PROVIDER).licence_scope,
        )

    def imported(self, original: Original, revision: str, downloaded_on: date) -> FileImport | None:
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
        self._store.raw.write(original.raw_path, original.source, original.sha256)
        self._store.raw.record(
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
    guide: SourceGuide = SOURCE_GUIDE,
) -> DatabentoImport:
    """Import a Databento batch-download folder or a single DBN file into `store`, with the
    session tables built in `cache_folder`, recording `imported_on` as the day its files were
    imported and the licence scope of Databento's entry in `guide`, and report what was
    imported."""
    importer = _DataFileImporter(store, cache_folder, instruments, imported_on, guide)
    if source.is_dir():
        return _import_batch(batch_in(source), store, importer)
    if source.is_file():
        return _import_file(source, store, importer)
    raise FileNotFoundError(
        f"Expected a Databento batch folder or DBN file, got no such path: {source}."
    )


def vendor_conditions(store: Store, job_id: str) -> pl.DataFrame:
    """The per-day conditions of a batch download the store keeps, from its `condition.json`:
    `date`, `condition` (available, degraded, pending, or missing), and the vendor's
    `last_modified_date`, sorted by date."""
    content = store.raw.read(PurePosixPath(PROVIDER, job_id, CONDITIONS_FILE_NAME))
    days = CONDITION_DAYS.validate_json(content)
    return pl.DataFrame(
        {
            "date": [day.day for day in days],
            "condition": [str(day.condition) for day in days],
            "last_modified_date": [day.last_modified_date for day in days],
        },
        schema={"date": pl.Date, "condition": pl.String, "last_modified_date": pl.Date},
    ).sort("date")


def _import_batch(batch: Batch, store: Store, importer: _DataFileImporter) -> DatabentoImport:
    _refuse_changed_originals(store, (*batch.sidecars, batch.data_file))
    unrecorded = [
        original
        for original in (*batch.sidecars, batch.data_file)
        if not _recorded(store, original)
    ]
    for original in unrecorded:
        require_published(original, batch.folder)
    raw_path = batch.data_file.raw_path.as_posix()
    report = None
    if batch.data_file in unrecorded:
        report = importer.imported(batch.data_file, f", {batch.revision()}", batch.downloaded_on)
    for sidecar in batch.sidecars:
        if sidecar in unrecorded:
            store.raw.write(sidecar.raw_path, sidecar.source, sidecar.sha256)
            store.raw.record(
                sidecar.raw_path,
                provider=PROVIDER,
                vendor_version=batch.revision(),
                downloaded_on=batch.downloaded_on,
                batch_job=sidecar.batch_job,
                imported_on=importer.imported_on,
                roots=(),
            )
    return DatabentoImport(
        source=str(batch.folder),
        batch=batch.report(),
        files=() if report is None else (report,),
        already_imported=() if batch.data_file in unrecorded else (raw_path,),
        daily_bars_skipped=(raw_path,) if batch.data_file in unrecorded and report is None else (),
    )


def _import_file(path: Path, store: Store, importer: _DataFileImporter) -> DatabentoImport:
    if not path.name.endswith(DBN_SUFFIXES):
        raise ValueError(
            f"Expected a DBN file ({', '.join(DBN_SUFFIXES)}) or a batch folder, got {path}: "
            "other exports arrive through `fefat data import file` (step 1.10)."
        )
    sha256 = sha256_of(path)
    original = Original(path, PurePosixPath(PROVIDER, sha256, path.name), sha256, None)
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


def _refuse_changed_originals(store: Store, originals: tuple[Original, ...]) -> None:
    """Refuse, before anything is written, files the raw manifest records with other bytes."""
    manifest = store.raw.manifest()
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


def _recorded(store: Store, original: Original) -> bool:
    return store.raw.manifest().file_at(original.raw_path.as_posix()) is not None
