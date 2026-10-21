"""Importing a trader's own file through an import profile (step 1.10, `02-engine-and-data.md`
§1.8), as `fefat data import file <path> --profile <name>` runs it.

`preview_file` reads and maps the whole file (`fefat.market.importers.profile_records`), runs
the calendar check on its records (`fefat.market.calendar_check.check_records`), and reports
the first rows as the store would hold them, the problems, the check, and the warnings, among
them a calendar that could not test the file's timing (`fefat.market.calendar_offset`), writing
nothing. `import_file` does the same, refuses a file with problems or whose records run late or
early against their calendar, and otherwise writes: the records, in the dataset
`<provider>/<schema>/root=<root>`, tagged `origin: import` with the licence scope of the
provider's source in the guide, through the partition buffers, so that an equal partition is
kept and a different one refused; then the new instrument the profile specifies, unless the
store has it; then the original file under `raw/user/<sha256>/<name>`, recorded in the raw
manifest last. The file is read once, for its hash and its rows. A file the raw manifest
records is imported already: importing it again changes nothing. Where imported and synced
data overlap, each provider keeps its own dataset. Nothing is uploaded anywhere.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

import polars as pl

from fefat.market.calendar import utc_text
from fefat.market.calendar_check import CalendarReport, check_records
from fefat.market.calendar_offset import TIMING_UNCHECKED, timing_checked
from fefat.market.dataset_choice import dataset_warnings
from fefat.market.importers.canonical import partition_key, partition_of
from fefat.market.importers.partition_buffers import PartitionBuffers
from fefat.market.importers.profile_contracts import ImportFacts
from fefat.market.importers.profile_records import MappedRecords, mapped_records
from fefat.market.importers.profiles import ImportProfile
from fefat.market.importers.tabular import read_table
from fefat.market.instruments import InstrumentTable
from fefat.market.layout import Dataset, DatasetMetadata, DatasetOrigin, Partition
from fefat.market.raw_manifest import checked_raw_path
from fefat.market.saved_instruments import save_instrument
from fefat.market.schema import FrozenModel, SchemaKind, Timeframe, TimeUnit, polars_schema
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
_NANO = 1_000_000_000


@dataclass(frozen=True)
class FileImportRequest:
    """One file to import: its path, its profile, and the contract, root, and time zone the
    command names, each None when it names none."""

    path: Path
    profile: ImportProfile
    contract: str | None = None
    root: str | None = None
    time_zone: str | None = None


class FileReading(FrozenModel):
    """What a file holds once read with its profile: the dataset its records go to, how many
    rows and records there are, their contracts and trade dates, what was left out, the
    problems, the calendar check, and the warnings: what every load of them repeats, and a
    calendar check that could not test their timing."""

    source: str
    profile: str
    dataset: Dataset
    rows_read: int
    records: int
    contracts: tuple[str, ...]
    first_trade_date: date | None
    last_trade_date: date | None
    bars_without_volume: int
    spread_rows: int
    problems: tuple[str, ...]
    calendar: CalendarReport
    warnings: tuple[str, ...]

    def refusals(self) -> list[str]:
        """The problems and offsets that stop an import."""
        return [*self.problems, *(offset.describe() for offset in self.calendar.offsets)]

    def lines(self) -> list[str]:
        dates = (
            "no trade date"
            if self.first_trade_date is None
            else (f"trade dates {self.first_trade_date} to {self.last_trade_date}")
        )
        contracts = ", ".join(self.contracts) if self.contracts else "none"
        left_out = [
            f"{self.bars_without_volume:,} bars without volume" if self.bars_without_volume else "",
            f"{self.spread_rows:,} rows of spread symbols" if self.spread_rows else "",
        ]
        shown = [part for part in left_out if part]
        return [
            f"  {self.rows_read:,} rows read; {self.records:,} records for {self.dataset.relative_folder()}, "
            f"contracts {contracts}, {dates}",
            *([f"  Left out: {' and '.join(shown)}"] if shown else []),
            *(f"  Warning: {warning}" for warning in self.warnings),
            *(["  Problems: none"] if not self.problems else ["  Problems:"]),
            *(f"    {problem}" for problem in self.problems),
            *(f"  Calendar check: {line}" for line in self.calendar.summary().splitlines()),
        ]


class FilePreview(FrozenModel):
    """A file read with its profile, nothing written, and its first records as stored."""

    reading: FileReading
    first_rows: tuple[str, ...]

    def summary(self) -> str:
        reading = self.reading
        heading = (
            f"Preview of {reading.source} with the profile {reading.profile}; nothing was written."
        )
        verdict = (
            "It would import as it is."
            if not reading.refusals()
            else "It would be refused: fix the profile, or the file, and preview it again."
        )
        return "\n".join(
            [heading, *reading.lines(), "  First records as stored:", *self.first_rows, verdict]
        )


class FileImportReport(FrozenModel):
    """What `import_file` wrote: the file kept under `raw`, what was read, the partitions
    written and those stored already, and whether the new instrument was saved."""

    source: str
    raw_path: str
    reading: FileReading
    partitions_written: int
    partitions_kept: int
    instrument_saved: bool

    def summary(self) -> str:
        saved = (
            ["  New instrument saved for later imports and loads."] if self.instrument_saved else []
        )
        return "\n".join(
            [
                f"Imported {self.source} with the profile {self.reading.profile}.",
                *self.reading.lines(),
                *saved,
                f"  Partitions: {self.partitions_written} written, {self.partitions_kept} already "
                "stored",
                f"  Original kept as raw/{self.raw_path}",
            ]
        )


class AlreadyImported(FrozenModel):
    """A file `import_file` found imported before, kept under `raw` as `raw_path`."""

    source: str
    raw_path: str

    def summary(self) -> str:
        return (
            f"Nothing to import from {self.source}: it is imported already, as raw/{self.raw_path}."
        )


def preview_file(
    request: FileImportRequest,
    instruments: InstrumentTable,
    cache_folder: Path,
    guide: SourceGuide = SOURCE_GUIDE,
) -> FilePreview:
    """The file read and checked as an import would, and nothing written."""
    mapped = _mapped(request, _file_bytes(request.path), instruments, cache_folder)
    reading = _reading(request, mapped)
    _metadata(request.profile, guide)
    return FilePreview(reading=reading, first_rows=tuple(_shown(mapped)))


def import_file(
    request: FileImportRequest,
    store: Store,
    cache_folder: Path,
    *,
    imported_on: date,
    instruments: InstrumentTable,
    guide: SourceGuide = SOURCE_GUIDE,
) -> FileImportReport | AlreadyImported:
    """Import the file into `store` (module docstring); a file with problems, or whose records
    run late or early against their calendar, is refused with them, and nothing is written."""
    content = _file_bytes(request.path)
    sha256 = hashlib.sha256(content).hexdigest()
    raw_path = PurePosixPath(USER_RAW_FOLDER, sha256, request.path.name)
    checked_raw_path(raw_path.as_posix())
    arguments = _import_arguments(request)
    recorded = store.raw_manifest().file_at(raw_path.as_posix())
    if recorded is not None:
        if recorded.vendor_version != arguments:
            raise ValueError(
                f"Expected {request.path} to be imported as it was on {recorded.imported_on}, "
                f"{recorded.vendor_version}, got {arguments}: a stored dataset never changes, "
                "so the first import stands."
            )
        return AlreadyImported(source=str(request.path), raw_path=raw_path.as_posix())
    mapped = _mapped(request, content, instruments, cache_folder)
    reading = _reading(request, mapped)
    _require_no_refusals(request, reading)
    buffers = PartitionBuffers(store, _clock(mapped), _metadata(request.profile, guide))
    buffers.add(_partitions(reading.dataset, mapped))
    buffers.write_all()
    saved = mapped.new_instrument and save_instrument(store.folder, mapped.instrument)
    store.write_raw_file(raw_path, request.path, sha256)
    store.record_raw_file(
        raw_path,
        provider=request.profile.provider,
        vendor_version=arguments,
        downloaded_on=datetime.fromtimestamp(request.path.stat().st_mtime, UTC).date(),
        batch_job=None,
        imported_on=imported_on,
        roots=(mapped.instrument.root,),
    )
    return FileImportReport(
        source=str(request.path),
        raw_path=raw_path.as_posix(),
        reading=reading,
        partitions_written=buffers.written,
        partitions_kept=buffers.kept,
        instrument_saved=saved,
    )


def _file_bytes(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(f"Expected a file to import, got no such file: {path}.")
    return path.read_bytes()


def _mapped(
    request: FileImportRequest, content: bytes, instruments: InstrumentTable, cache_folder: Path
) -> MappedRecords:
    file_name, table = read_table(request.path, content, request.profile.layout)
    facts = ImportFacts(
        file_name=file_name,
        contract=request.contract,
        root=request.root,
        time_zone=request.time_zone,
    )
    return mapped_records(table, request.profile, facts, instruments, cache_folder)


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
            *([TIMING_UNCHECKED] if unchecked else []),
        ),
    )


def _daily(profile: ImportProfile) -> bool:
    return isinstance(profile.timeframe, Timeframe) and profile.timeframe.unit is TimeUnit.DAY


def _import_arguments(request: FileImportRequest) -> str:
    """What besides the file decides its records, as the raw manifest records it: the profile,
    and the contract, root, and time zone the command named, if any."""
    # shortcut: a profile edited under its name is not told apart; record the profile's hash
    # when profiles get versions.
    named = (
        ("contract", request.contract),
        ("root", request.root),
        ("time zone", request.time_zone),
    )
    given = "".join(f", {name} {value}" for name, value in named if value is not None)
    return f"import profile {request.profile.name}{given}"


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
    the provider's source in the guide, or of the profile where the guide lacks the provider."""
    if profile.licence_scope is not None:
        scope = profile.licence_scope
    else:
        try:
            scope = guide.source_of_preset(profile.provider).licence_scope
        except ValueError as error:
            raise ValueError(
                f"Expected the profile {profile.name} to state its licence_scope, since the "
                f"source guide has no preset {profile.provider}: {error}"
            ) from error
    return DatasetMetadata(
        size_unit=profile.volume_unit,
        origin=DatasetOrigin.IMPORT,
        licence_scope=scope,
        series=profile.series,
    )


def _clock(mapped: MappedRecords) -> str:
    return "ts_open" if mapped.schema_name.kind is SchemaKind.OHLCV else "ts_recv"


def _partitions(dataset: Dataset, mapped: MappedRecords) -> dict[Partition, pl.DataFrame]:
    keyed = mapped.records.with_columns(partition_key=partition_key(mapped.schema_name))
    columns = polars_schema(mapped.schema_name).names()
    groups = keyed.partition_by("contract", "partition_key", as_dict=True, maintain_order=True)
    return {
        partition_of(dataset, str(contract), key): rows.select(columns)
        for (contract, key), rows in groups.items()
    }


def _shown(mapped: MappedRecords) -> list[str]:
    """The first records as the store holds them, instants in UTC and prices as decimals."""
    first = mapped.records.head(PREVIEW_ROWS)
    if mapped.schema_name.kind is SchemaKind.OHLCV:
        return [
            f"    {utc_text(row['ts_open'])} to {utc_text(row['ts_close'])}, {row['trade_date']}, "
            f"{row['contract']}: open {_decimal(row['open'])}, high {_decimal(row['high'])}, "
            f"low {_decimal(row['low'])}, close {_decimal(row['close'])}, volume {row['volume']}"
            for row in first.iter_rows(named=True)
        ]
    return [
        f"    {utc_text(row['ts_recv'])}, {row['trade_date']}, {row['contract']}: price "
        f"{_decimal(row['price'])}, size {row['size']}, side {row['side']}"
        for row in first.iter_rows(named=True)
    ]


def _decimal(nano: int) -> str:
    whole, part = divmod(abs(nano), _NANO)
    sign = "-" if nano < 0 else ""
    if part == 0:
        return f"{sign}{whole}"
    return f"{sign}{whole}.{part:09d}".rstrip("0")
