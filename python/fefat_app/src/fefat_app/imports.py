"""The import wizard's asks and answers (step 5.12, `01-architecture.md` section 7, D-93, D-101):
a file chosen in the browser and kept as an upload, or a path under the import roots of
`config.toml`; a profile named, a preset or one saved, or given whole, as the wizard builds one;
what is asked, a file's table, what its import would do, or the import itself; what the executor
runs, the path the server resolved in place of the client's text; and what it answers. A
preview's lists are cut to a few dozen entries beside their totals, and its texts to a few
hundred characters, since an execution's result holds 1 MiB (`fefat_app.executor.protocol`); an
import's result holds counts alone, since every job's is listed with the jobs. What a preview
quotes of a file goes to the client that asked, and nowhere else (D-21)."""

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field

from fefat.market.calendar_offset import OffsetCause
from fefat.market.importers.partition_merge import DifferingRecords
from fefat.market.importers.profiles import FileLayout, ImportProfile
from fefat.market.importers.report import DatasetMerge
from fefat.market.layout import Dataset, FolderName
from fefat.market.schema import FrozenModel
from fefat.market.snapshot import Sha256
from fefat_app.execution_kinds import ExecutionKind, ExecutionLimits

TABLE_ROWS = 20
"""How many of a file's rows its table shows, under the selects that map its columns."""
TABLE_COLUMNS = 64
"""How many of a file's columns its table shows."""
CELL_CHARS = 64
"""How much of a cell the table shows."""
LISTED_AT_MOST = 50
"""How many problems, contracts, or calendar mismatches a preview lists beside their total."""
LINE_CHARS = 300
"""How much of a problem, a mismatch, or a batch's line a preview shows."""
BATCH_LINES = 200
"""How many lines of a batch's account a preview shows."""
FIRST_RECORDS = 10
"""How many of a file's first records a preview shows as the store would hold them."""
PATH_CHARS = 4096
"""The longest path a client may type."""
WRITING_PERCENT = 40.0
"""An import job's progress once its file is read and it writes: a request to stop is refused
from here on, since a stopped import is finished only by running it again (ADR-0021)."""
CHECKING_PERCENT = 80.0
"""An import job's progress once its partitions are written, while it writes the quality
reports of what it imported."""

type Capped = Annotated[str, Field(max_length=LINE_CHARS)]


class SourceKind(StrEnum):
    """How the wizard names a file: an upload's id, or a path under the import roots."""

    UPLOAD = "upload"
    PATH = "path"


class ProfileChoiceKind(StrEnum):
    """How a request gives its profile: by the name of a preset or a saved profile, or whole."""

    NAMED = "named"
    GIVEN = "given"


class ReadKind(StrEnum):
    """What a preview or an import reads: a file's table, before a profile maps it, a trader's
    own file through a profile, or a Databento batch download or DBN file."""

    TABLE = "table"
    FILE = "file"
    DATABENTO = "databento"


class AnswerKind(StrEnum):
    """What the executor answers: a file's table, what a file's or a batch's import would do,
    what an import wrote, a file or batch imported before, or the SDK's refusal."""

    TABLE = "table"
    FILE = "file"
    DATABENTO = "databento"
    WROTE = "wrote"
    IMPORTED_BEFORE = "imported_before"
    REFUSED = "refused"


class ImportVerdict(StrEnum):
    """What a preview finds the import would do: import as it is, be refused for the problems
    or offsets found, be refused for records that differ from the store's, change nothing, as a
    file imported before, or import nothing, as a batch whose files hold nothing new."""

    IMPORTS = "imports"
    REFUSED = "refused"
    DIFFERING = "differing"
    IMPORTED_BEFORE = "imported_before"
    NOTHING = "nothing"


class UploadedFile(FrozenModel):
    """A file the browser sent, kept in its own folder of the workspace's uploads until its
    import has written: its id, its name, its size in bytes, its SHA-256, and when it came."""

    id: UUID
    name: str = Field(min_length=1)
    size: int = Field(ge=1)
    sha256: Sha256
    uploaded_at: AwareDatetime


class UploadSource(FrozenModel):
    """A file kept as an upload, named by its id."""

    kind: Literal[SourceKind.UPLOAD] = SourceKind.UPLOAD
    upload_id: UUID


class PathSource(FrozenModel):
    """A file or batch folder named by its path, which must lie under an import root."""

    kind: Literal[SourceKind.PATH] = SourceKind.PATH
    path: str = Field(min_length=1, max_length=PATH_CHARS)


type ImportSource = Annotated[UploadSource | PathSource, Field(discriminator="kind")]


class NamedProfile(FrozenModel):
    """A profile by its name: a preset, or a profile saved under `profiles/`."""

    kind: Literal[ProfileChoiceKind.NAMED] = ProfileChoiceKind.NAMED
    name: FolderName


class GivenProfile(FrozenModel):
    """A profile given whole, as the wizard builds a new one; it is kept under `profiles/`
    once an import with it has written."""

    kind: Literal[ProfileChoiceKind.GIVEN] = ProfileChoiceKind.GIVEN
    profile: ImportProfile


type ProfileChoice = Annotated[NamedProfile | GivenProfile, Field(discriminator="kind")]


class TableAsked(FrozenModel):
    """A file's table as `layout` reads it, or as its first lines suggest where it is None."""

    kind: Literal[ReadKind.TABLE] = ReadKind.TABLE
    source: ImportSource
    layout: FileLayout | None = None


class FileImportAsked(FrozenModel):
    """A trader's file through a profile, with the contract, the root, and the time zone the
    profile leaves to the import, as `fefat data import file` takes them, and what to do with
    records that differ from the store's."""

    kind: Literal[ReadKind.FILE] = ReadKind.FILE
    source: ImportSource
    profile: ProfileChoice
    contract: FolderName | None = None
    root: FolderName | None = None
    time_zone: str | None = Field(default=None, min_length=1, max_length=64)
    differing: DifferingRecords = DifferingRecords.REFUSE


class BatchImportAsked(FrozenModel):
    """A Databento batch download folder or DBN file, by its path, and what to do with records
    that differ from the store's."""

    kind: Literal[ReadKind.DATABENTO] = ReadKind.DATABENTO
    source: PathSource
    differing: DifferingRecords = DifferingRecords.REFUSE


type PreviewAsked = Annotated[
    TableAsked | FileImportAsked | BatchImportAsked, Field(discriminator="kind")
]
type ImportAsked = Annotated[FileImportAsked | BatchImportAsked, Field(discriminator="kind")]


class TableRequest(FrozenModel):
    """A file's table as the executor reads it, at the path the server resolved."""

    kind: Literal[ReadKind.TABLE] = ReadKind.TABLE
    path: Path
    layout: FileLayout | None


class FileRequest(FrozenModel):
    """A trader's file as the executor reads or imports it: the path the server resolved, the
    profile, which it keeps once its import has written where it was given whole, and the rest
    of the ask."""

    kind: Literal[ReadKind.FILE] = ReadKind.FILE
    path: Path
    profile: ImportProfile
    keep_profile: bool
    contract: str | None
    root: str | None
    time_zone: str | None
    differing: DifferingRecords


class BatchRequest(FrozenModel):
    """A Databento batch folder or DBN file as the executor reads or imports it."""

    kind: Literal[ReadKind.DATABENTO] = ReadKind.DATABENTO
    path: Path
    differing: DifferingRecords


type PreviewRequest = Annotated[
    TableRequest | FileRequest | BatchRequest, Field(discriminator="kind")
]
type ImportRequest = Annotated[FileRequest | BatchRequest, Field(discriminator="kind")]


class ImportPreviewSpec(FrozenModel):
    """A file or batch read for the wizard, nothing written: its table, or what its import
    would do, as `fefat data import --preview` reads it."""

    kind: Literal[ExecutionKind.IMPORT_PREVIEW] = ExecutionKind.IMPORT_PREVIEW
    request: PreviewRequest
    limits: ExecutionLimits


class ImportSpec(FrozenModel):
    """A file or batch imported into the store, as `fefat data import` imports it, each stage
    reported as it comes."""

    kind: Literal[ExecutionKind.IMPORT] = ExecutionKind.IMPORT
    request: ImportRequest
    limits: ExecutionLimits


class ImportJobPayload(FrozenModel):
    """An `import` job's payload: its import, and the upload it reads, which is removed once
    the import has written."""

    spec: ImportSpec
    upload_id: UUID | None


class TablePreview(FrozenModel):
    """A file's table: the name of the file its rows are in, its own or the one its `.gz` or
    `.zip` holds, the layout read, and its first columns and rows as text, cut to a cell's
    width, beside how many there are."""

    kind: Literal[AnswerKind.TABLE] = AnswerKind.TABLE
    file_name: str
    layout: FileLayout
    columns: tuple[str, ...] = Field(max_length=TABLE_COLUMNS)
    columns_total: int = Field(ge=0)
    rows: tuple[tuple[str | None, ...], ...] = Field(max_length=TABLE_ROWS)
    rows_total: int = Field(ge=0)


class OffsetDirection(StrEnum):
    """Whether a file's records run late or early against their calendar."""

    LATE = "late"
    EARLY = "early"


class OffsetSeen(FrozenModel):
    """A file's offset from its calendar (`fefat.market.calendar_offset.CalendarOffset`): what
    it points at, which way and how far its records run, in words, on which trade dates, and
    the SDK's line for it."""

    cause: OffsetCause
    direction: OffsetDirection
    duration: str
    first_trade_date: date
    last_trade_date: date
    description: Capped


class RecordsKind(StrEnum):
    """Whether a file holds bars or prints."""

    BARS = "bars"
    PRINTS = "prints"


class BarSeen(FrozenModel):
    """A bar as the store would hold it, its instants in ISO 8601 UTC and its prices in the
    instrument's units."""

    ts_open: str
    ts_close: str
    trade_date: date
    contract: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class PrintSeen(FrozenModel):
    """A print as the store would hold it, its instant in ISO 8601 UTC and its price in the
    instrument's units."""

    ts_recv: str
    trade_date: date
    contract: str
    price: float
    size: int
    side: str


class FirstBars(FrozenModel):
    """A file's first bars as the store would hold them."""

    kind: Literal[RecordsKind.BARS] = RecordsKind.BARS
    rows: tuple[BarSeen, ...] = Field(max_length=FIRST_RECORDS)


class FirstPrints(FrozenModel):
    """A file's first prints as the store would hold them."""

    kind: Literal[RecordsKind.PRINTS] = RecordsKind.PRINTS
    rows: tuple[PrintSeen, ...] = Field(max_length=FIRST_RECORDS)


class FileSeen(FrozenModel):
    """What a file's import would do (`fefat.market.importers.file_report.FilePreview`): the
    verdict; the file's name and profile; the dataset its records go to; what was read, left
    out, and found; the calendar's check, with each offset; the first records as stored; and
    what the file adds to its dataset, or the raw copy of a file imported before."""

    kind: Literal[AnswerKind.FILE] = AnswerKind.FILE
    verdict: ImportVerdict
    file_name: str
    profile: str
    dataset: Dataset
    rows_read: int = Field(ge=0)
    records: int = Field(ge=0)
    contracts: tuple[str, ...] = Field(max_length=LISTED_AT_MOST)
    contracts_total: int = Field(ge=0)
    first_trade_date: date | None
    last_trade_date: date | None
    bars_without_volume: int = Field(ge=0)
    spread_rows: int = Field(ge=0)
    problems: tuple[Capped, ...] = Field(max_length=LISTED_AT_MOST)
    problems_total: int = Field(ge=0)
    days_checked: int = Field(ge=0)
    offsets: tuple[OffsetSeen, ...] = Field(max_length=LISTED_AT_MOST)
    mismatches: tuple[Capped, ...] = Field(max_length=LISTED_AT_MOST)
    mismatches_total: int = Field(ge=0)
    warnings: tuple[Capped, ...] = Field(max_length=LISTED_AT_MOST)
    first_records: Annotated[FirstBars | FirstPrints, Field(discriminator="kind")]
    merge: DatasetMerge | None
    raw_path: str | None


class BatchSeen(FrozenModel):
    """What a Databento batch's import would do (`fefat.market.importers.report.
    DatabentoPreview`): the verdict, the account's lines, counts and dates alone, and what each
    of its files adds to each dataset."""

    kind: Literal[AnswerKind.DATABENTO] = AnswerKind.DATABENTO
    verdict: ImportVerdict
    lines: tuple[Capped, ...] = Field(max_length=BATCH_LINES)
    merges: tuple[DatasetMerge, ...]


class RefusedImport(FrozenModel):
    """What the SDK refused, in its words, as a file it cannot read or a profile that does not
    fit it."""

    kind: Literal[AnswerKind.REFUSED] = AnswerKind.REFUSED
    message: str


type ImportPreviewAnswer = Annotated[
    TablePreview | FileSeen | BatchSeen | RefusedImport, Field(discriminator="kind")
]


class DatasetWritten(FrozenModel):
    """What an import wrote into one dataset: the records it added, those the store held
    already, those of the file taken in place of stored ones, and the trade dates new to it."""

    dataset: Dataset
    records_added: int = Field(ge=0)
    records_held: int = Field(ge=0)
    records_taken: int = Field(ge=0)
    new_sessions: int = Field(ge=0)


class ImportWrote(FrozenModel):
    """What an import wrote: each dataset's account, whether the profile's new instrument was
    saved, and whether the profile given whole was kept under `profiles/`."""

    kind: Literal[AnswerKind.WROTE] = AnswerKind.WROTE
    datasets: tuple[DatasetWritten, ...]
    instrument_saved: bool
    profile_kept: bool


class ImportedBefore(FrozenModel):
    """A file, or every file of a batch, the raw manifest records: importing it again changes
    nothing."""

    kind: Literal[AnswerKind.IMPORTED_BEFORE] = AnswerKind.IMPORTED_BEFORE


type ImportAnswer = Annotated[
    ImportWrote | ImportedBefore | RefusedImport, Field(discriminator="kind")
]


class ImportPreviewOutput(FrozenModel):
    """What an import's preview gives."""

    kind: Literal[ExecutionKind.IMPORT_PREVIEW] = ExecutionKind.IMPORT_PREVIEW
    answer: ImportPreviewAnswer


class ImportOutput(FrozenModel):
    """What an import gives."""

    kind: Literal[ExecutionKind.IMPORT] = ExecutionKind.IMPORT
    answer: ImportAnswer


class ProfileOrigin(StrEnum):
    """Where a profile comes from: FEFAT's presets, or the trader's `profiles/` folder."""

    PRESET = "preset"
    SAVED = "saved"


class ListedProfile(FrozenModel):
    """A profile the wizard offers, with where it comes from."""

    origin: ProfileOrigin
    profile: ImportProfile


class NoSuchUploadError(ValueError):
    """An upload's id that no kept upload has."""

    def __init__(self, upload_id: UUID) -> None:
        super().__init__(
            f"Expected the id of a file kept for an import, got {upload_id}: choose the file again."
        )


class UploadRefusedError(ValueError):
    """A file the server does not keep: its name, or an empty body."""


class PathRefusedError(ValueError):
    """A path outside the import roots, or of a kind the importers do not read."""


class ProfileNameTakenError(ValueError):
    """A profile given whole under a name a preset or another saved profile has."""
