"""The import wizard's preview and import in the runner (step 5.12, D-93): a file's table read as
its profile would read it (`fefat.market.importers.tabular.read_table`), what a file's or a
batch's import would do (`preview_file`, `preview_databento`), and the import itself
(`import_file`, `import_databento`), each as `fefat data import` runs it, here, never in the
server, so that a file too large, or an archive that unpacks past the memory limit, ends the
runner alone. What the SDK refuses, and what a file it cannot read raises, a broken archive's
error among them (`REFUSALS`), comes back as the runner's answer, in its words, kept to its first
`ERROR_CHARS` characters; an import reports each stage it reaches as the execution's progress,
and keeps a profile given whole once it has written (`keep_profile`), or says why it could not,
though the records are imported."""

import os
import zipfile
import zlib
from collections.abc import Iterable
from datetime import UTC, datetime
from functools import partial
from itertools import islice
from pathlib import Path

import polars as pl

from fefat.config import resolve_paths
from fefat.market.calendar import utc_text
from fefat.market.calendar_breaks import BreaksWithBars
from fefat.market.calendar_offset import CalendarOffset, duration_text
from fefat.market.engine_units import PRICE_SCALE
from fefat.market.importers.databento import import_databento, preview_databento
from fefat.market.importers.file_import import FileImportRequest, import_file, preview_file
from fefat.market.importers.file_report import (
    AlreadyImported,
    FileImportReport,
    FilePreview,
    StoredBar,
    StoredPrint,
)
from fefat.market.importers.profiles import keep_profile
from fefat.market.importers.report import DatabentoPreview, DatasetMerge, ImportStage
from fefat.market.importers.tabular import read_table, sniffed_layout
from fefat.market.saved_instruments import instrument_table
from fefat.market.schema import SchemaKind
from fefat.market.store import Store
from fefat_app.execution import ExecutionProgress, ProgressReport
from fefat_app.executor.protocol import ERROR_CHARS
from fefat_app.imports import (
    BATCH_LINES,
    CELL_CHARS,
    CHECKING_MESSAGE,
    CHECKING_PERCENT,
    FIRST_RECORDS,
    LINE_CHARS,
    LISTED_AT_MOST,
    TABLE_COLUMNS,
    TABLE_ROWS,
    WRITING_MESSAGE,
    WRITING_PERCENT,
    BarSeen,
    BatchSeen,
    BreaksSeen,
    DatasetWritten,
    FileRequest,
    FileSeen,
    FirstBars,
    FirstPrints,
    ImportedBefore,
    ImportOutput,
    ImportPreviewOutput,
    ImportPreviewSpec,
    ImportRequest,
    ImportSpec,
    ImportVerdict,
    ImportWrote,
    MergeSeen,
    OffsetDirection,
    OffsetSeen,
    PreviewRequest,
    PrintSeen,
    RefusedImport,
    TablePreview,
    TableRequest,
)

STAGES = {
    ImportStage.FILE_READ: (WRITING_PERCENT, WRITING_MESSAGE),
    ImportStage.PARTITIONS_WRITTEN: (CHECKING_PERCENT, CHECKING_MESSAGE),
}
"""The percent and the message of each stage an import reaches, the message saying what it does
next."""
REFUSALS = (
    ValueError,
    OSError,
    EOFError,
    zipfile.BadZipFile,
    zlib.error,
    pl.exceptions.PolarsError,
)
"""What a preview and an import answer as refused, in the error's words: the SDK's refusals, a
file that cannot be read, a `.gz` cut short, an archive that is none, and Polars' errors."""


def import_preview_output(spec: ImportPreviewSpec) -> ImportPreviewOutput:
    """What `spec`'s file or batch holds, or the SDK's refusal of it."""
    try:
        return ImportPreviewOutput(answer=_previewed(spec.request))
    except REFUSALS as refused:
        return ImportPreviewOutput(answer=RefusedImport(message=str(refused)[:ERROR_CHARS]))


def import_output(spec: ImportSpec, report: ProgressReport) -> ImportOutput:
    """What `spec`'s import wrote, each stage reported as it comes, or the SDK's refusal."""
    try:
        return ImportOutput(answer=_imported(spec.request, report))
    except REFUSALS as refused:
        return ImportOutput(answer=RefusedImport(message=str(refused)[:ERROR_CHARS]))


def _previewed(request: PreviewRequest) -> TablePreview | FileSeen | BatchSeen:
    if isinstance(request, TableRequest):
        return _table(request)
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    instruments = instrument_table(store.folder)
    if isinstance(request, FileRequest):
        preview = preview_file(
            _file_request(request), store, instruments, paths.cache_dir, differing=request.differing
        )
        return _file_seen(preview, request.path.name)
    batch = preview_databento(
        request.path, store, paths.cache_dir, instruments=instruments, differing=request.differing
    )
    return _batch_seen(batch)


def _imported(request: ImportRequest, report: ProgressReport) -> ImportWrote | ImportedBefore:
    paths = resolve_paths(os.environ)
    store = Store(paths.data_dir)
    instruments = instrument_table(store.folder)
    imported_on = datetime.now(UTC).date()
    told = partial(_told, report)
    if isinstance(request, FileRequest):
        imported = import_file(
            _file_request(request),
            store,
            paths.cache_dir,
            imported_on=imported_on,
            instruments=instruments,
            differing=request.differing,
            progress=told,
        )
        return _file_wrote(imported, request, paths.profiles_dir)
    batch = import_databento(
        request.path,
        store,
        paths.cache_dir,
        imported_on=imported_on,
        instruments=instruments,
        differing=request.differing,
        progress=told,
    )
    if not batch.files:
        return ImportedBefore()
    written = tuple(_written(merge) for file in batch.files for merge in file.merges)
    return ImportWrote(
        datasets=written, instrument_saved=False, profile_kept=False, profile_refusal=None
    )


def _told(report: ProgressReport, stage: ImportStage) -> None:
    percent, message = STAGES[stage]
    report(ExecutionProgress(percent=percent, message=message, details={}))


def _file_wrote(
    imported: FileImportReport | AlreadyImported, request: FileRequest, profiles_dir: Path
) -> ImportWrote | ImportedBefore:
    """What the file's import wrote, its profile kept where it was given whole, or why it was
    not, as when another import kept another profile under its name meanwhile: the records are
    imported all the same."""
    if isinstance(imported, AlreadyImported):
        return ImportedBefore()
    kept, refusal = False, None
    if request.keep_profile:
        try:
            kept = keep_profile(request.profile, profiles_dir)
        except (ValueError, OSError) as refused:
            refusal = str(refused)[:LINE_CHARS]
    return ImportWrote(
        datasets=(_written(imported.merge, imported.reading.left_out),),
        instrument_saved=imported.instrument_saved,
        profile_kept=kept,
        profile_refusal=refusal,
    )


def _table(request: TableRequest) -> TablePreview:
    """The file's first rows and columns as text, laid out as asked, or as its first lines
    suggest."""
    content = request.path.read_bytes()
    layout = sniffed_layout(request.path, content) if request.layout is None else request.layout
    name, table = read_table(request.path, content, layout)
    shown = table.select(table.columns[:TABLE_COLUMNS]).head(TABLE_ROWS)
    rows = tuple(tuple(_cell(cell) for cell in row) for row in shown.iter_rows())
    return TablePreview(
        file_name=name,
        layout=layout,
        columns=tuple(shown.columns),
        columns_total=table.width,
        rows=rows,
        rows_total=table.height,
    )


def _file_seen(preview: FilePreview, file_name: str) -> FileSeen:
    reading, found = preview.reading, preview.against_the_store
    calendar = reading.calendar
    return FileSeen(
        verdict=_file_verdict(preview),
        file_name=file_name,
        profile=reading.profile,
        dataset=reading.dataset,
        rows_read=reading.rows_read,
        records=reading.records,
        breaks_with_bars=_breaks_seen(reading.calendar.breaks_with_bars, reading.left_out),
        contracts=reading.contracts[:LISTED_AT_MOST],
        contracts_total=len(reading.contracts),
        first_trade_date=reading.first_trade_date,
        last_trade_date=reading.last_trade_date,
        bars_without_volume=reading.bars_without_volume,
        spread_rows=reading.spread_rows,
        problems=_listed(reading.problems),
        problems_total=len(reading.problems),
        days_checked=calendar.days_checked,
        offsets=tuple(_offset_seen(offset) for offset in calendar.offsets[:LISTED_AT_MOST]),
        mismatches=_listed(mismatch.describe() for mismatch in calendar.mismatches),
        mismatches_total=len(calendar.mismatches),
        warnings=_listed(reading.warnings),
        first_records=_first_records(preview),
        merge=_merge_seen(found) if isinstance(found, DatasetMerge) else None,
        raw_path=found.raw_path if isinstance(found, AlreadyImported) else None,
    )


def _file_verdict(preview: FilePreview) -> ImportVerdict:
    found = preview.against_the_store
    if isinstance(found, AlreadyImported):
        return ImportVerdict.IMPORTED_BEFORE
    if preview.reading.only_bars_in_breaks_refuse():
        return ImportVerdict.BARS_IN_BREAKS
    if preview.reading.refusals():
        return ImportVerdict.REFUSED
    if found is not None and found.refuses():
        return ImportVerdict.DIFFERING
    return ImportVerdict.IMPORTS


def _breaks_seen(
    found: tuple[BreaksWithBars, ...], left_out: BreaksWithBars | None
) -> BreaksSeen | None:
    """A file's breaks with a bar closing at the next open in counts and trade dates, those
    its reading found, or those its import leaves out, after which the records it takes hold
    none (ADR-0022); none without them."""
    if left_out is not None and found:
        raise ValueError(
            "Expected no bar in a break closing at the next open among the records left without "
            f"the sessions beside such breaks, got {found[0].describe()}."
        )
    seen = left_out if left_out is not None else next(iter(found), None)
    if seen is None:
        return None
    return BreaksSeen(
        left_out=left_out is not None,
        bars=seen.bars(),
        breaks=tuple(each.after for each in seen.breaks[:LISTED_AT_MOST]),
        breaks_total=len(seen.breaks),
        sessions=tuple(seen.trade_dates_beside()[:LISTED_AT_MOST]),
        sessions_total=len(seen.sessions_beside),
        records=seen.records_beside(),
    )


def _batch_seen(preview: DatabentoPreview) -> BatchSeen:
    return BatchSeen(
        verdict=_batch_verdict(preview),
        lines=_listed(preview.lines(), BATCH_LINES),
        merges=tuple(_merge_seen(merge) for file in preview.files for merge in file.merges),
    )


def _merge_seen(merge: DatasetMerge) -> MergeSeen:
    """What a file adds to a dataset, in counts, its differing trade dates cut, since a batch of
    many products holds a session per product and trade date."""
    return MergeSeen(
        dataset=merge.dataset,
        records_added=merge.records_added,
        records_held=merge.records_held,
        records_differing=merge.records_differing,
        stored_records_disputed=merge.stored_records_disputed,
        new_sessions=len(merge.new_sessions),
        extended_sessions=len(merge.extended_sessions),
        differing_sessions=tuple(
            day.trade_date for day in merge.differing_sessions[:LISTED_AT_MOST]
        ),
        differing_sessions_total=len(merge.differing_sessions),
        partitions_changed=merge.partitions_changed,
        partitions_unchanged=merge.partitions_unchanged,
    )


def _batch_verdict(preview: DatabentoPreview) -> ImportVerdict:
    if preview.refuses():
        return ImportVerdict.DIFFERING
    if preview.files:
        return ImportVerdict.IMPORTS
    if preview.already_imported:
        return ImportVerdict.IMPORTED_BEFORE
    return ImportVerdict.NOTHING


def _offset_seen(offset: CalendarOffset) -> OffsetSeen:
    late = offset.nanoseconds > 0
    return OffsetSeen(
        cause=offset.cause,
        direction=OffsetDirection.LATE if late else OffsetDirection.EARLY,
        duration=duration_text(abs(offset.nanoseconds)),
        first_trade_date=offset.first_trade_date,
        last_trade_date=offset.last_trade_date,
        description=offset.describe()[:LINE_CHARS],
    )


def _first_records(preview: FilePreview) -> FirstBars | FirstPrints:
    """The file's first records, as bars or prints by its dataset's schema."""
    records = preview.first_records[:FIRST_RECORDS]
    if preview.reading.dataset.schema_name.kind is SchemaKind.OHLCV:
        return FirstBars(rows=tuple(_bar(bar) for bar in records if isinstance(bar, StoredBar)))
    prints = tuple(_print(each) for each in records if isinstance(each, StoredPrint))
    return FirstPrints(rows=prints)


def _bar(bar: StoredBar) -> BarSeen:
    return BarSeen(
        ts_open=utc_text(bar.ts_open),
        ts_close=utc_text(bar.ts_close),
        trade_date=bar.trade_date,
        contract=bar.contract,
        open=bar.open / PRICE_SCALE,
        high=bar.high / PRICE_SCALE,
        low=bar.low / PRICE_SCALE,
        close=bar.close / PRICE_SCALE,
        volume=bar.volume,
    )


def _print(stored: StoredPrint) -> PrintSeen:
    return PrintSeen(
        ts_recv=utc_text(stored.ts_recv),
        trade_date=stored.trade_date,
        contract=stored.contract,
        price=stored.price / PRICE_SCALE,
        size=stored.size,
        side=stored.side,
    )


def _written(merge: DatasetMerge, left_out: BreaksWithBars | None = None) -> DatasetWritten:
    """What an import wrote into a dataset, with the records it left out beside the file's
    breaks with bars, if any (ADR-0022)."""
    return DatasetWritten(
        dataset=merge.dataset,
        records_added=merge.records_added,
        records_held=merge.records_held,
        records_taken=merge.records_differing if merge.replaces() else 0,
        new_sessions=len(merge.new_sessions),
        records_left_out=0 if left_out is None else left_out.records_beside(),
    )


def _file_request(request: FileRequest) -> FileImportRequest:
    return FileImportRequest(
        path=request.path,
        profile=request.profile,
        contract=request.contract,
        root=request.root,
        time_zone=request.time_zone,
        bars_in_breaks=request.bars_in_breaks,
    )


def _listed(texts: Iterable[str], most: int = LISTED_AT_MOST) -> tuple[str, ...]:
    """The first `most` of `texts`, each cut to `LINE_CHARS`."""
    return tuple(text[:LINE_CHARS] for text in islice(texts, most))


def _cell(cell: object) -> str | None:
    """A cell of the table, text since `read_table` reads every column as text, cut to
    `CELL_CHARS`."""
    return None if cell is None else str(cell)[:CELL_CHARS]
