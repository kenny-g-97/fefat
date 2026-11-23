"""The import wizard's asks and answers (step 5.12, `01-architecture.md` section 7, D-93, D-101):
a file chosen in the browser and kept as an upload, or a path under the import roots of
`config.toml`; a profile named, a preset or one saved, or given whole, as the wizard builds one;
what is asked, a file's table, what its import would do, or the import itself, of one file or
of several in one round (D-102); what the executor runs, the path the server resolved in place
of the client's text; and what it answers. A
preview's lists are cut to a few dozen entries beside their totals, and its texts to a few
hundred characters, since an execution's result holds 1 MiB (`fefat_app.executor.protocol`); an
import's result holds counts alone, since every job's is listed with the jobs, and a
round's the name of each file it left out with why, the text a file's failed job gives as
its error. What a preview
quotes of a file goes to the client that asked, and nowhere else (D-21)."""

from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from fefat.market.calendar_breaks import BarsInBreaks
from fefat.market.calendar_offset import OffsetCause
from fefat.market.importers.partition_merge import DifferingRecords
from fefat.market.importers.profiles import FileLayout, ImportProfile
from fefat.market.layout import Dataset, FolderName
from fefat.market.schema import FrozenModel
from fefat.market.snapshot import Sha256
from fefat_app.execution_kinds import ExecutionKind, ExecutionLimits

TABLE_ROWS = 10
"""How many of a file's rows its table shows, under the selects that map its columns: enough to
read the columns by, and few enough that the review stays near the fields."""
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
UPLOAD_RECORD_NAME = "upload.json"
"""The record of a kept upload, beside its file, a name no upload may take."""
FILES_AT_MOST = 200
"""How many files one import takes in a round (D-102), each with the upload limit of
`config.toml`."""
WRITING_PERCENT = 40.0
"""An import job's progress once its file is read and it writes: a request to stop is refused
from here on, since a stopped import is finished only by running it again (ADR-0021)."""
CHECKING_PERCENT = 80.0
"""An import job's progress once its partitions are written, while it writes the quality
reports of what it imported."""
WRITING_MESSAGE = "Writing the partitions"
"""An import job's message from its file read, as it writes."""
CHECKING_MESSAGE = "Checking the quality of what was imported"
"""An import job's message once its partitions are written."""

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
    own file through a profile, several of them in one round through one profile, which an
    import alone takes (D-102), or a Databento batch download or DBN file."""

    TABLE = "table"
    FILE = "file"
    FILES = "files"
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
    or offsets found, be refused for its bars in a break alone, which the trader may leave out
    with the sessions beside them (ADR-0022), be refused for records that differ from the
    store's, change nothing, as a file imported before, or import nothing, as a batch whose files
    hold nothing new."""

    IMPORTS = "imports"
    REFUSED = "refused"
    BARS_IN_BREAKS = "bars_in_breaks"
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
    bars_in_breaks: BarsInBreaks = BarsInBreaks.REFUSE


class FilesImportAsked(FrozenModel):
    """Several of a trader's files in one import (D-102), through one profile, as several
    commands of `fefat data import file` with the same options would take them: no contract,
    since each file's name gives its own; at most `FILES_AT_MOST`."""

    kind: Literal[ReadKind.FILES] = ReadKind.FILES
    sources: tuple[ImportSource, ...] = Field(min_length=1, max_length=FILES_AT_MOST)
    profile: ProfileChoice
    root: FolderName | None = None
    time_zone: str | None = Field(default=None, min_length=1, max_length=64)
    differing: DifferingRecords = DifferingRecords.REFUSE
    leaving_out_bars_in_breaks: tuple[ImportSource, ...] = Field(
        default=(), max_length=FILES_AT_MOST
    )

    @model_validator(mode="after")
    def _bars_left_out_of_files_it_imports(self) -> Self:
        stray = [source for source in self.leaving_out_bars_in_breaks if source not in self.sources]
        if stray:
            raise ValueError(
                "Expected the files whose bars in a break are left out among the files the "
                f"round imports, got {len(stray)} beside them."
            )
        return self

    def bars_in_breaks_of(self, source: ImportSource) -> BarsInBreaks:
        """What the round does with the bars in a break of the file `source` (ADR-0022)."""
        if source in self.leaving_out_bars_in_breaks:
            return BarsInBreaks.LEAVE_OUT
        return BarsInBreaks.REFUSE


class BatchImportAsked(FrozenModel):
    """A Databento batch download folder or DBN file, by its path, and what to do with records
    that differ from the store's."""

    kind: Literal[ReadKind.DATABENTO] = ReadKind.DATABENTO
    source: PathSource
    differing: DifferingRecords = DifferingRecords.REFUSE


type PreviewAsked = Annotated[
    TableAsked | FileImportAsked | BatchImportAsked, Field(discriminator="kind")
]
type ImportAsked = Annotated[
    FileImportAsked | FilesImportAsked | BatchImportAsked, Field(discriminator="kind")
]


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
    bars_in_breaks: BarsInBreaks = BarsInBreaks.REFUSE


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


class RoundFile(FrozenModel):
    """A file of a round (D-102): the path the server resolved, the upload it reads, if it is
    one, and what its import does with its bars in a break (ADR-0022)."""

    path: Path
    upload_id: UUID | None
    bars_in_breaks: BarsInBreaks = BarsInBreaks.REFUSE


class ImportJobPayload(FrozenModel):
    """An `import` job's payload: its import, and the upload it reads, which is removed once
    the import has written; `in_round` for the files of a round (D-102), the first in `spec`,
    and the others, each imported as the first is, its path in place of the first's."""

    spec: ImportSpec
    upload_id: UUID | None
    others: tuple[RoundFile, ...] = Field(default=(), max_length=FILES_AT_MOST - 1)
    in_round: bool = False

    @model_validator(mode="after")
    def _a_round_of_files_through_a_profile(self) -> Self:
        if self.others and not self.in_round:
            raise ValueError("Expected the files of a round, got other files beside one import.")
        if self.in_round and not isinstance(self.spec.request, FileRequest):
            raise ValueError(
                f"Expected a round of files through a profile, got a {self.spec.request.kind} "
                "import."
            )
        return self

    def files(self) -> tuple[tuple[ImportSpec, UUID | None], ...]:
        """Each file's import and the upload it reads: the first's, then each other's."""
        others = ((self._spec_of(other), other.upload_id) for other in self.others)
        return ((self.spec, self.upload_id), *others)

    def _spec_of(self, other: RoundFile) -> ImportSpec:
        """The first file's import, of the file `other`, with its own choice for its bars in a
        break."""
        update = {"path": other.path, "bars_in_breaks": other.bars_in_breaks}
        request = self.spec.request.model_copy(update=update)
        return self.spec.model_copy(update={"request": request})


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


class MergeSeen(FrozenModel):
    """What a file adds to one dataset FEAT holds (`fefat.market.importers.report.
    DatasetMerge`), in counts: its records new, held, and differing, with the stored records at
    the instants the two dispute; its sessions new to the store and those the store held part
    of; the first trade dates with differing records, beside their total; and the partitions
    the import changes and leaves as they are."""

    dataset: Dataset
    records_added: int = Field(ge=0)
    records_held: int = Field(ge=0)
    records_differing: int = Field(ge=0)
    stored_records_disputed: int = Field(ge=0)
    new_sessions: int = Field(ge=0)
    extended_sessions: int = Field(ge=0)
    differing_sessions: tuple[date, ...] = Field(max_length=LISTED_AT_MOST)
    differing_sessions_total: int = Field(ge=0)
    partitions_changed: int = Field(ge=0)
    partitions_unchanged: int = Field(ge=0)


class BreaksSeen(FrozenModel):
    """A file's breaks that hold a bar closing at the next open, the edge of a stretch a
    platform stamped early (`fefat.market.calendar_breaks.BreaksWithBars`, ADR-0022), in counts
    and trade dates: whether its import leaves them out, the bars in them, the trade dates they
    follow, the sessions beside them, and the other sessions whose last bar ends a bar before the
    close, which the correction leaves out with them (D-104), the first of each beside their
    totals, and the records of every session left out, the bars among them."""

    left_out: bool
    bars: int = Field(ge=1)
    breaks: tuple[date, ...] = Field(min_length=1, max_length=LISTED_AT_MOST)
    breaks_total: int = Field(ge=1)
    sessions: tuple[date, ...] = Field(min_length=1, max_length=LISTED_AT_MOST)
    sessions_total: int = Field(ge=1)
    ending_a_bar_early: tuple[date, ...] = Field(max_length=LISTED_AT_MOST)
    ending_a_bar_early_total: int = Field(ge=0)
    records: int = Field(ge=1)


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
    breaks_with_bars: BreaksSeen | None
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
    merge: MergeSeen | None
    raw_path: str | None


class BatchSeen(FrozenModel):
    """What a Databento batch's import would do (`fefat.market.importers.report.
    DatabentoPreview`): the verdict, the account's lines, counts and dates alone, and what each
    of its files adds to each dataset, in counts, a dataset a product and schema of the batch."""

    kind: Literal[AnswerKind.DATABENTO] = AnswerKind.DATABENTO
    verdict: ImportVerdict
    lines: tuple[Capped, ...] = Field(max_length=BATCH_LINES)
    merges: tuple[MergeSeen, ...]


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
    already, those of the file taken in place of stored ones, the trade dates new to it, and
    the records it left out, the file's bars in a break and the sessions beside them, which a
    round adds up over files whose sessions may share trade dates (ADR-0022)."""

    dataset: Dataset
    records_added: int = Field(ge=0)
    records_held: int = Field(ge=0)
    records_taken: int = Field(ge=0)
    new_sessions: int = Field(ge=0)
    records_left_out: int = Field(default=0, ge=0)


class ImportWrote(FrozenModel):
    """What an import wrote: each dataset's account, none where a batch held no record FEAT
    stores; whether the profile's new instrument was saved; and whether the profile given whole
    was kept under `profiles/`, or why it was not, though its records were imported."""

    kind: Literal[AnswerKind.WROTE] = AnswerKind.WROTE
    datasets: tuple[DatasetWritten, ...]
    instrument_saved: bool
    profile_kept: bool
    profile_refusal: Capped | None


class NotImported(FrozenModel):
    """A file a round of several left out (D-102), with its upload, if it is one, and why."""

    upload_id: UUID | None
    file_name: str
    message: Capped


class RoundFiles(FrozenModel):
    """What a round did with its files (D-102): those imported, those imported before, and
    each it left out, which the wizard offers to review again."""

    files_imported: int = Field(ge=0)
    files_imported_before: int = Field(ge=0)
    not_imported: tuple[NotImported, ...] = Field(max_length=FILES_AT_MOST)


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


REPORT_FAILED = "then its quality report failed"
"""What an import's error says where it wrote its data and only its report failed, which importing
the file again would not write (step 5.19)."""


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


class ProfileRefusedError(ValueError):
    """A profile given whole under a name a preset or another saved profile has, or a saved
    profile's file, edited by hand, that no longer reads as a profile."""
