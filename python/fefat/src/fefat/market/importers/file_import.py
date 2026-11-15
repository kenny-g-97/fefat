"""Importing a trader's own file through an import profile (step 1.10, `02-engine-and-data.md`
§1.8), as `fefat data import file <path> --profile <name>` runs it.

`preview_file` reads and maps the whole file (`fefat.market.importers.profile_records`), runs
the calendar check on its records (`fefat.market.calendar_check.check_records`), and reports
the first rows as the store would hold them, the problems, the check, and the warnings, among
them a calendar that could not test the file's timing (`fefat.market.calendar_offset`), and,
for a file that reads without problems, what it would add to its dataset, writing nothing.
`import_file` does the same, refuses a file with problems or whose records run late or
early against their calendar, and otherwise reads each partition of its records, in the dataset
`<provider>/<schema>/root=<root>`, against what the store holds of it (ADR-0021): records the
store lacks are added, those it holds are counted, and those it holds with other values refuse
the file, unless the import lets the file's stand. Only then does it write, once nothing can
refuse the file any more, holding the store's import lock, for which another import's writes
wait (step 5.12): the original file under `raw/user/<sha256>/<name>`, its copy checked
against its hash; the new instrument the profile specifies, unless the store has it; the
partitions its records change, a new dataset tagged `origin: import` with the licence scope of
the provider's source in the guide; and, last, the file's entry in the raw manifest. The file is
read once, for its hash and its rows, and its partitions are gone over to check and, where one
changes, again to write. A file the raw manifest records is imported already: importing it
again changes nothing.
Where imported and synced data overlap, each provider keeps its own dataset. Nothing is uploaded
anywhere.
"""

import hashlib
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

import polars as pl

from fefat.market.calendar_check import check_records
from fefat.market.calendar_offset import TIMING_UNCHECKED, timing_checked
from fefat.market.dataset_choice import dataset_warnings
from fefat.market.importers.canonical import partition_key, partition_of
from fefat.market.importers.file_report import (
    AlreadyImported,
    FileImportReport,
    FilePreview,
    FileReading,
    StoredBar,
    StoredPrint,
)
from fefat.market.importers.partition_buffers import (
    DIFFERING_TAKEN_RECORDED,
    MergeTally,
    PartitionBuffers,
    require_none_differing,
    require_one_price_basis,
    write_merges,
)
from fefat.market.importers.partition_merge import (
    DifferingRecords,
    PartitionMerge,
    RecordIdentity,
    whole_at_the_files_edges,
)
from fefat.market.importers.profile_contracts import ImportFacts
from fefat.market.importers.profile_records import (
    MappedRecords,
    mapped_records,
    tick_arrival_offset,
)
from fefat.market.importers.profiles import ImportProfile
from fefat.market.importers.report import DatasetMerge, ImportProgress, ImportStage, tell_no_one
from fefat.market.importers.tabular import read_table
from fefat.market.instruments import InstrumentTable
from fefat.market.layout import Dataset, DatasetMetadata, DatasetOrigin, Partition, SeriesKind
from fefat.market.raw_manifest import checked_raw_path
from fefat.market.saved_instruments import instrument_is_saved, save_instrument
from fefat.market.schema import SchemaKind, Timeframe, TimeUnit, polars_schema
from fefat.market.sources import SOURCE_GUIDE, SourceGuide
from fefat.market.store import Store

USER_RAW_FOLDER = "user"
"""The folder under `raw` that keeps a trader's own files."""
PREVIEW_ROWS = 10
DAILY_SESSION_ASSUMED = (
    "each daily bar is stored as its calendar session, open to close, which the calendar cannot "
    "check: a bar of a UTC day or of regular hours only would carry prices from outside its "
    "session, so compare one bar's open and close with the platform's session settings"
)
"""The warning of every daily import: a daily bar names its session by its date alone."""
PRINTS_AT_THE_END_OF_THEIR_STAMP = (
    "the prints are stamped to the second, millisecond, or microsecond, so each is stored at "
    "the end of its stamp, the latest instant it can have arrived, and comes after every "
    "decision inside it; its minute, and so every bar, stays as the file has it"
)
"""The warning of an import of prints stamped coarser than a nanosecond (D-70)."""
PRINTS_AT_THE_END_OF_THEIR_STAMP_RECORDED = ", prints received at the end of their stamp"
"""How the raw manifest records that rule among an import's arguments, so that a file imported
before it is refused rather than read as imported (D-50, D-70)."""


@dataclass(frozen=True)
class FileImportRequest:
    """One file to import: its path, its profile, and the contract, root, and time zone the
    command names, each None when it names none."""

    path: Path
    profile: ImportProfile
    contract: str | None = None
    root: str | None = None
    time_zone: str | None = None


def preview_file(
    request: FileImportRequest,
    store: Store,
    instruments: InstrumentTable,
    cache_folder: Path,
    guide: SourceGuide = SOURCE_GUIDE,
    differing: DifferingRecords | str = DifferingRecords.REFUSE,
) -> FilePreview:
    """The file read and checked against `store` as `import_file` would under `differing`, the
    option or its text, and nothing written: what it holds, and what it would add to its
    dataset, or that it is imported already. What refuses its import before the store's records
    are compared refuses the preview too: a file imported before under other arguments, a
    dataset of another unit or series, and the records no merge takes (ADR-0021)."""
    differing = DifferingRecords(differing)
    content = _file_bytes(request.path)
    raw_path = _raw_path(request, hashlib.sha256(content).hexdigest())
    imported = _imported_before(store, request, raw_path, _import_arguments(request))
    mapped = _mapped(request, content, instruments, cache_folder)
    reading = _reading(request, mapped)
    metadata = _metadata(request.profile, guide)
    against_the_store = None
    if imported:
        against_the_store = AlreadyImported(source=str(request.path), raw_path=raw_path.as_posix())
    elif not reading.refusals():
        partitions = _partitions(reading.dataset, mapped)
        merging = _FileMerge(store, partitions, _identity(request.profile), metadata)
        against_the_store = merging.checked(differing)
    return FilePreview(
        reading=reading, first_records=_first_records(mapped), against_the_store=against_the_store
    )


def import_file(
    request: FileImportRequest,
    store: Store,
    cache_folder: Path,
    *,
    imported_on: date,
    instruments: InstrumentTable,
    guide: SourceGuide = SOURCE_GUIDE,
    differing: DifferingRecords | str = DifferingRecords.REFUSE,
    progress: ImportProgress = tell_no_one,
) -> FileImportReport | AlreadyImported:
    """Import the file into `store`, merging its records into the partitions it overlaps
    (module docstring); a file with problems, whose records run late or early against their
    calendar, or whose records differ from the store's while `differing`, the option or its
    text (`"take-file"`), does not let the file's stand, is refused with them, and nothing is
    written. Once the file is checked and its copy under `raw` verified, the last of what can
    refuse it, the import writes under the store's import lock (`Store.held_for_an_import`),
    telling `progress` each stage it reaches (step 5.12)."""
    differing = DifferingRecords(differing)
    content = _file_bytes(request.path)
    sha256 = hashlib.sha256(content).hexdigest()
    raw_path = _raw_path(request, sha256)
    arguments = _import_arguments(request)
    imported = AlreadyImported(source=str(request.path), raw_path=raw_path.as_posix())
    if _imported_before(store, request, raw_path, arguments):
        return imported
    mapped = _mapped(request, content, instruments, cache_folder)
    reading = _reading(request, mapped)
    _require_no_refusals(request, reading)
    merging = _FileMerge(
        store=store,
        partitions=_partitions(reading.dataset, mapped),
        identity=_identity(request.profile),
        metadata=_metadata(request.profile, guide),
    )
    merge = merging.checked(differing)
    require_none_differing([merge], request.path)
    unsaved = mapped.new_instrument and not instrument_is_saved(store.folder, mapped.instrument)
    progress(ImportStage.FILE_READ)
    store.raw.write(raw_path, request.path, sha256)
    with store.held_for_an_import():
        if _imported_before(store, request, raw_path, arguments):
            return imported
        saved = unsaved and save_instrument(store.folder, mapped.instrument)
        if merge.partitions_changed:
            merging.write(differing)
        version = f"{arguments}{_taken(differing)}"
        _record(store, request, raw_path, version, imported_on, mapped.instrument.root)
    progress(ImportStage.PARTITIONS_WRITTEN)
    return FileImportReport(
        source=str(request.path),
        raw_path=raw_path.as_posix(),
        reading=reading,
        merge=merge,
        instrument_saved=saved,
    )


@dataclass(frozen=True)
class _FileMerge:
    """A file's rows by partition read against one store, gone over once to check and count,
    and again to write, with one merged partition in memory at a time."""

    store: Store
    partitions: Mapping[Partition, pl.DataFrame]
    identity: RecordIdentity
    metadata: DatasetMetadata

    def checked(self, on_differing: DifferingRecords) -> DatasetMerge:
        """What the file adds to its dataset under `on_differing`, nothing written; a file the
        store cannot take is refused here, as is, whatever `on_differing` says, a file that
        shares no bar with the back-adjusted series the store holds of its dataset
        (`require_one_price_basis`)."""
        tally = MergeTally(on_differing)
        for merge in self._merges():
            tally.add(merge)
        (added,) = tally.datasets()
        adjusted = self.metadata.series is SeriesKind.CONTINUOUS_BACK_ADJUSTED
        if adjusted and self.store.list_partitions(added.dataset):
            require_one_price_basis(added)
        return added

    def write(self, differing: DifferingRecords) -> None:
        """Write the partitions the file changes."""
        write_merges(self.store, self._merges(), self.metadata, differing)

    def _merges(self) -> Iterator[PartitionMerge]:
        """Each partition's merge, in both passes; prints numbered by their place are refused
        where they dispute an instant their file may hold part of (`partition_merge`)."""
        buffers = PartitionBuffers(self.store, self.identity, self.metadata)
        buffers.add(self.partitions)
        if not self.identity.numbered_by_place:
            return buffers.rest()
        return whole_at_the_files_edges(buffers.rest(), self.partitions, self.identity.clock)


def _raw_path(request: FileImportRequest, sha256: str) -> PurePosixPath:
    """Where the file is kept under `raw`: by its hash, since two exports can share a name."""
    return PurePosixPath(USER_RAW_FOLDER, sha256, request.path.name)


def _taken(differing: DifferingRecords) -> str:
    """What the raw manifest adds to an import's arguments where it took the file's records."""
    return DIFFERING_TAKEN_RECORDED if differing is DifferingRecords.TAKE_THE_FILE else ""


def _record(
    store: Store,
    request: FileImportRequest,
    raw_path: PurePosixPath,
    vendor_version: str,
    imported_on: date,
    root: str,
) -> None:
    """The file's entry in the raw manifest, the import's last write: its provider, the
    arguments that decided its records, the day its file was last written, and its root."""
    store.raw.record(
        raw_path,
        provider=request.profile.provider,
        vendor_version=vendor_version,
        downloaded_on=datetime.fromtimestamp(request.path.stat().st_mtime, UTC).date(),
        batch_job=None,
        imported_on=imported_on,
        roots=(root,),
    )


def _imported_before(
    store: Store, request: FileImportRequest, raw_path: PurePosixPath, arguments: str
) -> bool:
    """Whether the raw manifest records the file, which is refused where it was imported under
    other arguments (D-50): its records are in the store as that import read them."""
    recorded = store.raw.manifest().file_at(checked_raw_path(raw_path.as_posix()))
    if recorded is None:
        return False
    if recorded.vendor_version.removesuffix(DIFFERING_TAKEN_RECORDED) != arguments:
        raise ValueError(
            f"Expected {request.path} to be imported as it was on {recorded.imported_on}, "
            f"{recorded.vendor_version}, got {arguments}: a file is imported once, as its first "
            "import read it."
        )
    return True


def _file_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"Expected a file to import, got no such file: {path}.")
    return path.read_bytes()


def _mapped(
    request: FileImportRequest, content: bytes, instruments: InstrumentTable, cache_folder: Path
) -> MappedRecords:
    """The file's records read with its profile; what Polars refuses to read, a refusal in
    words that says what to check, never a traceback (step 5.12, from `BACKLOG.md`)."""
    try:
        file_name, table = read_table(request.path, content, request.profile.layout)
        facts = ImportFacts(
            file_name=file_name,
            contract=request.contract,
            root=request.root,
            time_zone=request.time_zone,
        )
        return mapped_records(table, request.profile, facts, instruments, cache_folder)
    except pl.exceptions.PolarsError as error:
        raise ValueError(_refused_by_polars(request, error)) from error


_POLARS_SAYS = (
    ("found more fields than defined", "a row of more fields than the first"),
    ("invalid utf-8", "text that is not UTF-8, as a file saved as Unicode or UTF-16 is"),
)
"""What Polars' refusals of a file mean, in the trader's words, by the start of its message."""


def _refused_by_polars(request: FileImportRequest, error: pl.exceptions.PolarsError) -> str:
    layout = request.profile.layout
    header = "a header row" if layout.header else "no header row"
    said = str(error).splitlines()[0]
    meant = next((words for start, words in _POLARS_SAYS if said.startswith(start)), None)
    got = f"Polars' refusal: {said}" if meant is None else meant
    return (
        f"Expected {request.path.name} to read with the profile {request.profile.name}, its "
        f"fields separated by {layout.delimiter!r} and {header}, got {got}: check the "
        "profile's delimiter and header row against the file, and that the file is the export "
        "the profile describes."
    )


def _reading(request: FileImportRequest, mapped: MappedRecords) -> FileReading:
    profile = request.profile
    dataset = Dataset(
        provider=profile.provider, schema_name=mapped.schema_name, root=mapped.instrument.root
    )
    records = mapped.records
    dates = records.select(pl.col("trade_date").min(), pl.col("trade_date").max().alias("last"))
    first, last = dates.row(0) if not records.is_empty() else (None, None)
    calendar = check_records(dataset, records.lazy(), mapped.sessions)
    unchecked = not calendar.offsets and not timing_checked(dataset, records, mapped.sessions)
    return FileReading(
        source=str(request.path),
        profile=profile.name,
        dataset=dataset,
        rows_read=mapped.rows_read,
        records=records.height,
        contracts=tuple(sorted(records.get_column("contract").unique().to_list())),
        first_trade_date=first,
        last_trade_date=last,
        bars_without_volume=mapped.bars_without_volume,
        spread_rows=mapped.spread_rows,
        problems=tuple(problem.describe() for problem in mapped.problems),
        calendar=calendar,
        warnings=(
            *dataset_warnings(dataset, profile.series),
            *([DAILY_SESSION_ASSUMED] if _daily(profile) else []),
            *([PRINTS_AT_THE_END_OF_THEIR_STAMP] if tick_arrival_offset(profile) else []),
            *([TIMING_UNCHECKED] if unchecked else []),
        ),
    )


def _daily(profile: ImportProfile) -> bool:
    return isinstance(profile.timeframe, Timeframe) and profile.timeframe.unit is TimeUnit.DAY


def _import_arguments(request: FileImportRequest) -> str:
    """What besides the file decides its records, as the raw manifest records it: the profile,
    the contract, root, and time zone the command named, if any, and whether its prints are
    received at the end of their stamp (D-70)."""
    # shortcut: a profile edited under its name is not told apart; record the profile's hash
    # when profiles get versions.
    named = (
        ("contract", request.contract),
        ("root", request.root),
        ("time zone", request.time_zone),
    )
    given = "".join(f", {name} {value}" for name, value in named if value is not None)
    stamped = (
        PRINTS_AT_THE_END_OF_THEIR_STAMP_RECORDED if tick_arrival_offset(request.profile) else ""
    )
    return f"import profile {request.profile.name}{given}{stamped}"


def _require_no_refusals(request: FileImportRequest, reading: FileReading) -> None:
    refusals = reading.refusals()
    if not refusals:
        return
    listed = "\n".join(f"  {refusal}" for refusal in refusals)
    raise ValueError(
        f"Expected {request.path} to read with the profile {request.profile.name} without "
        f"problems, got:\n{listed}\nNothing was written; --preview shows the records."
    )


def _metadata(profile: ImportProfile, guide: SourceGuide) -> DatasetMetadata:
    """The dataset's metadata: the profile's volume unit and series, and the licence scope of
    the provider's source in the guide, its preset's or the source it names (step 5.12), or of
    the profile where the guide lacks the provider."""
    if profile.licence_scope is not None:
        scope = profile.licence_scope
    else:
        try:
            scope = guide.source_of_provider(profile.provider).licence_scope
        except ValueError as error:
            raise ValueError(
                f"Expected the profile {profile.name} to state its licence_scope, since the "
                f"source guide has no preset or source {profile.provider}: {error}"
            ) from error
    return DatasetMetadata(
        size_unit=profile.volume_unit,
        origin=DatasetOrigin.IMPORT,
        licence_scope=scope,
        series=profile.series,
    )


def _identity(profile: ImportProfile) -> RecordIdentity:
    """What tells the profile's records apart: a bar's open, or a print's receive time and
    place, the print numbered by its place where the profile maps no sequence of its own."""
    if profile.bar_timeframe() is not None:
        return RecordIdentity(clock="ts_open")
    ticks = profile.columns.ticks
    return RecordIdentity(
        clock="ts_recv", numbered_by_place=ticks is None or ticks.sequence is None
    )


def _partitions(dataset: Dataset, mapped: MappedRecords) -> dict[Partition, pl.DataFrame]:
    keyed = mapped.records.with_columns(partition_key=partition_key(mapped.schema_name))
    columns = polars_schema(mapped.schema_name).names()
    groups = keyed.partition_by("contract", "partition_key", as_dict=True, maintain_order=True)
    return {
        partition_of(dataset, str(contract), key): rows.select(columns)
        for (contract, key), rows in groups.items()
    }


def _first_records(mapped: MappedRecords) -> tuple[StoredBar, ...] | tuple[StoredPrint, ...]:
    """The first records as the store holds them."""
    first = mapped.records.head(PREVIEW_ROWS)
    if mapped.schema_name.kind is SchemaKind.OHLCV:
        bars = first.select(list(StoredBar.model_fields))
        return tuple(StoredBar.model_validate(row) for row in bars.iter_rows(named=True))
    prints = first.select(list(StoredPrint.model_fields))
    return tuple(StoredPrint.model_validate(row) for row in prints.iter_rows(named=True))
