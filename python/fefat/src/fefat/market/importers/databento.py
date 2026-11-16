"""Importing Databento's files (`02-engine-and-data.md` §1.8, D-38): a batch download, which is
the DBN files beside the vendor's `metadata.json`, `manifest.json`, and `condition.json`, or a
single DBN file (`.dbn`, `.dbn.zst`). No network and no key: a purchase is made and downloaded on
the vendor's website, and its files come through here.

`import_databento` checks every file it is about to read against the SHA-256 the batch's
`manifest.json` publishes, refusing a mismatch with both hashes, before it writes anything; a
batch split into several DBN files is refused (`fefat.market.importers.databento_batch`). It
reads the data file three times, streaming: for the days each instrument has records, which name
its contracts; to check every partition against what the store holds of it, counting what the
file adds, what the store already holds, and what differs (`file_writer.checked_records`,
ADR-0021); and, once nothing refuses the file, under the store's import lock, for which
another import's writes wait (step 5.12), to write the partitions that change, merged
with the stored ones, a reading that a file which changes none is spared, each new dataset's
`dataset.json` naming its origin, an import, and the licence scope of Databento's entry in the
source guide (`fefat.market.sources`). The file is kept unchanged under
`raw/databento/<job>/` (a single file under `raw/databento/<its SHA-256>/`, since the vendor
names files by dates and schema, not by product), copied once the check has passed and before
the first partition is written, with its entry in the raw manifest recorded last: the job id
and the published SHA-256, the DBN version and the newest revision date in `condition.json`
(`DBN 3, revised 2026-09-23`), followed by `, the file's records taken where they differ` where
the import was told that they stand, the download date the job id carries, or, for a single
file, the UTC date it was last written, the day of the import, and the roots whose records the
file held (none for the sidecars). So a refused file leaves the store as it was, an import cut
short while it writes is finished by running it again, and a finished one imports nothing twice
and reads none of its files again.
A file the raw manifest records with other bytes is refused: raw files never change, so a
corrected download arrives as a new file. The vendor's daily bars (`ohlcv-1d`) are cut on UTC
days rather than sessions and are skipped (ADR-0019). `preview_databento` finds and checks the
same files, reads the data file twice, and writes nothing: it says what the import would add.
`vendor_conditions` reads a batch's per-day conditions back for the quality report (1.8).

    paths = resolve_paths(os.environ)
    today = datetime.now(UTC).date()
    report = import_databento(
        Path("market_data/MNQ"), Store(paths.data_dir), paths.cache_dir, imported_on=today
    )
    print(report.summary())
"""

from dataclasses import dataclass, replace
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
from fefat.market.importers.file_writer import checked_records, write_records
from fefat.market.importers.partition_buffers import (
    CONTRACT_SIZE,
    DIFFERING_TAKEN_RECORDED,
    require_none_differing,
)
from fefat.market.importers.partition_merge import DifferingRecords
from fefat.market.importers.report import (
    DatabentoFiles,
    DatabentoImport,
    DatabentoPreview,
    FileImport,
    ImportProgress,
    ImportStage,
    tell_no_one,
)
from fefat.market.instruments import STATIC_TABLE, InstrumentTable
from fefat.market.layout import DatasetMetadata, DatasetOrigin
from fefat.market.raw_manifest import checked_raw_path
from fefat.market.schema import parse_schema_name
from fefat.market.sources import SOURCE_GUIDE, SourceGuide
from fefat.market.store import Store

__all__ = ["PROVIDER", "import_databento", "preview_databento", "vendor_conditions"]

_DAILY_BARS = parse_schema_name("ohlcv-1d")


@dataclass(frozen=True)
class _Download:
    """A folder or file found and checked before its data file is read: against the raw
    manifest, which refuses a recorded file whose bytes changed, and against the hashes its
    batch publishes. `recorded` says that the raw manifest holds the data file, which is then
    imported already."""

    source: Path
    batch: Batch | None
    data_file: Original
    recorded: bool
    downloaded_on: date

    def revision(self) -> str:
        """What the raw manifest adds to the data file's DBN version: its batch's revision."""
        return "" if self.batch is None else f", {self.batch.revision()}"

    def reported[Report: DatabentoFiles](
        self, kind: type[Report], file: FileImport | None
    ) -> Report:
        """The report of `kind` on the download, `file` being what its data file adds to the
        store, none where the file is recorded, or holds the vendor's daily bars, which are
        skipped."""
        raw_path = self.data_file.raw_path.as_posix()
        return kind(
            source=str(self.source),
            batch=None if self.batch is None else self.batch.report(),
            files=() if file is None else (file,),
            already_imported=(raw_path,) if self.recorded else (),
            daily_bars_skipped=() if self.recorded or file is not None else (raw_path,),
        )


class _DataFileImporter:
    """Imports DBN data files into one store, dating their records by the calendars in the
    cache folder, naming their contracts within the instrument table, and settling the records
    that differ from the store's as `differing` says, the option or its text."""

    def __init__(
        self,
        store: Store,
        cache_folder: Path,
        instruments: InstrumentTable,
        guide: SourceGuide,
        differing: DifferingRecords | str,
    ) -> None:
        self._store = store
        self._cache_folder = cache_folder
        self._instruments = instruments
        self._differing = DifferingRecords(differing)
        self._metadata = DatasetMetadata(
            size_unit=CONTRACT_SIZE,
            origin=DatasetOrigin.IMPORT,
            licence_scope=guide.source_of_preset(PROVIDER).licence_scope,
        )

    def checked(self, original: Original) -> tuple[RecordPlacement, FileImport] | None:
        """The file read against the store, nothing written: how its records are placed, and
        what it would add to each dataset; `None` for the vendor's daily bars, which are
        skipped. The file is read twice, streaming: once for the days each instrument has
        records, which name its contracts, then to check its partitions."""
        metadata, frames = read_dbn(original.source)
        if metadata.schema_name == _DAILY_BARS:
            return None
        days = active_days(frames, metadata.schema_name)
        placement = RecordPlacement(
            original.source, metadata, days, PROVIDER, self._instruments, self._cache_folder
        )
        return placement, self.checked_again(original, placement)

    def checked_again(self, original: Original, placement: RecordPlacement) -> FileImport:
        """The file's records, placed as they were, read against the store in a reading of
        their own: what they would add to each dataset, as another import's writes meanwhile
        left the store."""
        _, frames = read_dbn(original.source)
        raw_path = original.raw_path.as_posix()
        return checked_records(
            frames, placement, self._store, raw_path, self._metadata, self._differing
        )

    def written(
        self,
        download: _Download,
        checked: tuple[RecordPlacement, FileImport],
        imported_on: date,
    ) -> FileImport:
        """The download's data file, `checked` whole and not refused and kept under `raw`, the
        partitions it changes written in a third reading, of the verified copy under `raw`,
        which a file that changes none is spared, and its entry in the raw manifest recorded
        last, with `imported_on`."""
        original = download.data_file
        placement, report = checked
        if any(merge.partitions_changed for merge in report.merges):
            _, frames = read_dbn(self._store.raw.copy_of(original.raw_path))
            write_records(frames, placement, self._store, self._metadata, self._differing)
        taken = self._differing is DifferingRecords.TAKE_THE_FILE
        version = f"DBN {placement.metadata.version}{download.revision()}"
        self._store.raw.record(
            original.raw_path,
            provider=PROVIDER,
            vendor_version=f"{version}{DIFFERING_TAKEN_RECORDED if taken else ''}",
            downloaded_on=download.downloaded_on,
            batch_job=original.batch_job,
            imported_on=imported_on,
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
    differing: DifferingRecords | str = DifferingRecords.REFUSE,
    progress: ImportProgress = tell_no_one,
) -> DatabentoImport:
    """Import a Databento batch-download folder or a single DBN file into `store`, merging its
    records into the partitions it overlaps (ADR-0021), with the session tables built in
    `cache_folder`, recording `imported_on` as the day its files were imported and the licence
    scope of Databento's entry in `guide`, and report what was imported. Records the store
    holds with other values refuse the file, nothing written, unless `differing`, the option or
    its text (`"take-file"`), lets the file's stand. Once the data file is checked and its copy
    under `raw` verified, the last of what can refuse it before then, so that a file refused
    takes no lock, the import writes under the store's import lock (`Store.held_for_an_import`):
    there the data file is looked up again as imported, and checked again where another import
    wrote into the store meanwhile, before its partitions, read from that copy, and the batch's
    sidecars; `progress` is told each stage it reaches (step 5.12)."""
    importer = _DataFileImporter(store, cache_folder, instruments, guide, differing)
    download = _download(source, store)
    original = download.data_file
    listed = store.list_partitions()
    checked = None if download.recorded else importer.checked(original)
    if checked is not None:
        require_none_differing(checked[1].merges, original.source)
    sidecars = () if download.batch is None else download.batch.sidecars
    if checked is None and all(_recorded(store, sidecar) for sidecar in sidecars):
        return download.reported(DatabentoImport, None)
    if checked is not None:
        store.raw.write(original.raw_path, original.source, original.sha256)
    with store.held_for_an_import():
        if checked is not None and _recorded(store, original):
            return replace(download, recorded=True).reported(DatabentoImport, None)
        if checked is not None and store.list_partitions() != listed:
            checked = (checked[0], importer.checked_again(original, checked[0]))
            require_none_differing(checked[1].merges, original.source)
        progress(ImportStage.FILE_READ)
        file = None if checked is None else importer.written(download, checked, imported_on)
        if download.batch is not None:
            _keep_the_sidecars(download.batch, store, imported_on)
    progress(ImportStage.PARTITIONS_WRITTEN)
    return download.reported(DatabentoImport, file)


def preview_databento(
    source: Path,
    store: Store,
    cache_folder: Path,
    *,
    instruments: InstrumentTable = STATIC_TABLE,
    guide: SourceGuide = SOURCE_GUIDE,
    differing: DifferingRecords | str = DifferingRecords.REFUSE,
) -> DatabentoPreview:
    """What `import_databento` would do with the folder or file under `differing`, the option
    or its text, and nothing written, a batch's sidecars included: the same files found and
    checked, and the data file read against `store`. What refuses the import before the store's
    records are compared refuses the preview too."""
    importer = _DataFileImporter(store, cache_folder, instruments, guide, differing)
    download = _download(source, store)
    checked = None if download.recorded else importer.checked(download.data_file)
    return download.reported(DatabentoPreview, None if checked is None else checked[1])


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


def _download(source: Path, store: Store) -> _Download:
    if source.is_dir():
        return _batch_download(batch_in(source), store)
    if source.is_file():
        return _file_download(source, store)
    raise FileNotFoundError(
        f"Expected a Databento batch folder or DBN file, got no such path: {source}."
    )


def _batch_download(batch: Batch, store: Store) -> _Download:
    originals = (*batch.sidecars, batch.data_file)
    _refuse_changed_originals(store, originals)
    unrecorded = [original for original in originals if not _recorded(store, original)]
    for original in unrecorded:
        require_published(original, batch.folder)
    return _Download(
        source=batch.folder,
        batch=batch,
        data_file=batch.data_file,
        recorded=batch.data_file not in unrecorded,
        downloaded_on=batch.downloaded_on,
    )


def _file_download(path: Path, store: Store) -> _Download:
    if not path.name.endswith(DBN_SUFFIXES):
        raise ValueError(
            f"Expected a DBN file ({', '.join(DBN_SUFFIXES)}) or a batch folder, got {path}: "
            "other exports arrive through `fefat data import file` (step 1.10)."
        )
    sha256 = sha256_of(path)
    original = Original(path, PurePosixPath(PROVIDER, sha256, path.name), sha256, None)
    checked_raw_path(original.raw_path.as_posix())
    return _Download(
        source=path,
        batch=None,
        data_file=original,
        recorded=_recorded(store, original),
        downloaded_on=datetime.fromtimestamp(path.stat().st_mtime, UTC).date(),
    )


def _keep_the_sidecars(batch: Batch, store: Store, imported_on: date) -> None:
    """Keep under `raw`, and record, each sidecar of the batch that the raw manifest lacks,
    after the batch's data file."""
    for sidecar in batch.sidecars:
        if _recorded(store, sidecar):
            continue
        store.raw.write(sidecar.raw_path, sidecar.source, sidecar.sha256)
        store.raw.record(
            sidecar.raw_path,
            provider=PROVIDER,
            vendor_version=batch.revision(),
            downloaded_on=batch.downloaded_on,
            batch_job=sidecar.batch_job,
            imported_on=imported_on,
            roots=(),
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
