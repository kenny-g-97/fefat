"""An import as a job (step 5.12, `01-architecture.md` section 6, D-93): its payload an
`ImportJobPayload`, the import run by the worker's executor as `fefat data import` runs it, never in
the server, each stage the runner reports a `progress` event of the job's stream, and a request to
stop read each second until the file is read; then, in the worker, the quality report of each
provider's data of each root it wrote, as the catalog sync writes them
(`fefat_app.jobs.catalog_sync.written_report`), the profiles indexed where the import kept one,
and last the upload's folder removed, since the copy under `raw/user/` is the import's record.

Once its file is read the import writes, and the jobs refuse a request to stop
(`fefat_app.services.jobs.STOPPABLE_BELOW`): the report that it writes clears a request made
before it in the same write, tried again while the database is busy (`JobProgress.
advance_past_stopping`), so that neither the worker nor the reaper ends an import that writes,
but for a request read in the moment between the runner's report and the worker's. A refusal of
the SDK ends the job failed in its words, and a failure once the import wrote says what was
written and how to finish it, with the end of the runner's error, where its exception is named.
The result holds counts alone, since every job's is listed with the jobs, and a round's the
name of each file it left out with why.

A round of several files (D-102) imports them one after another, each in a runner of its own: a file
the SDK refuses, or whose runner fails, runs out of time, or cannot start, is left out with why, and
the round goes on. Until a file writes, the files read take the job to `WRITING_PERCENT`, and a
request to stop stops the round between two files; from the first file that writes, the round is
past stopping, and the files done take it on to `CHECKING_PERCENT`. The quality reports are written
once, at the round's end, of every product a file wrote, and only the uploads of the files imported,
now or before, are removed. A round of which some file was left out and none wrote fails with the
reason of a file that stopped while it wrote, else of the first left out, its uploads kept for
another round; one whose reports fail says how many files it imported."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fefat.config import FefatPaths
from fefat.market.layout import Dataset
from fefat.market.store import Store
from fefat_app.execution import ExecutionProgress, ProgressReport, StopCheck
from fefat_app.executor.protocol import ERROR_CHARS
from fefat_app.imports import (
    CHECKING_MESSAGE,
    CHECKING_PERCENT,
    LINE_CHARS,
    REPORT_FAILED,
    WRITING_PERCENT,
    DatasetWritten,
    ImportAnswer,
    ImportedBefore,
    ImportJobPayload,
    ImportOutput,
    ImportSpec,
    ImportWrote,
    NotImported,
    RefusedImport,
    RoundFiles,
)
from fefat_app.jobs.catalog_sync import written_report
from fefat_app.jobs.executions import (
    ExecutionFailedError,
    ExecutionTimedOutError,
    advancing,
    executed,
)
from fefat_app.jobs.progress import JobProgress, tried_while_busy
from fefat_app.ports import Executor, UploadRecords

READING_MESSAGE = "Reading the file"
"""An import job's message until its file is read."""
STOPPED_WHILE_WRITING = (
    "The import stopped while it wrote, and importing the file again finishes it: "
)
"""What a job's error says first where its import stopped once it wrote (ADR-0021)."""

type FileAnswer = ImportWrote | ImportedBefore | NotImported
"""What a round did with one of its files."""


@dataclass(frozen=True)
class ImportJobs:
    """The work of an `import` job (module docstring): the import run by `executor`, the quality
    reports of `store` written in the folders of `paths`, the profiles indexed by
    `index_profiles`, and the upload removed from `uploads`."""

    executor: Executor
    store: Store
    paths: FefatPaths
    index_profiles: Callable[[], object]
    uploads: UploadRecords

    def run(self, payload: Mapping[str, Any], progress: JobProgress) -> dict[str, Any]:
        """Run the import of `payload`, reporting through `progress`; its result, or the error
        the job ends with. The upload stays where the import was refused or did not end, for the
        import to be run again, and goes once it wrote, after its reports."""
        job = ImportJobPayload.model_validate(payload)
        if job.in_round:
            return self._round(job, progress)
        progress.advance(0, READING_MESSAGE)
        following = _Stages(progress)
        answer = following.imported(self.executor, job.spec)
        if isinstance(answer, RefusedImport):
            raise ExecutionFailedError(_said(answer.message, following.writing))
        try:
            if isinstance(answer, ImportedBefore):
                return answer.model_dump(mode="json")
            reports = self._reports(answer, "The file was imported")
            return {**answer.model_dump(mode="json"), "reports": reports}
        finally:
            self._upload_removed(job.upload_id)

    def _round(self, job: ImportJobPayload, progress: JobProgress) -> dict[str, Any]:
        """The files of `job` imported in one round (module docstring): what they wrote, added
        up, and under `round` how many were imported, how many were imported before, and those
        left out."""
        files = job.files()
        following = _Round(progress, len(files))
        answered = [
            (upload_id, following.imported(self.executor, spec, upload_id))
            for spec, upload_id in files
        ]
        answers = [answer for _, answer in answered]
        left = [answer for answer in answers if isinstance(answer, NotImported)]
        wrote = [answer for answer in answers if isinstance(answer, ImportWrote)]
        if left and not wrote:
            raise ExecutionFailedError(_none_imported(left, len(files)))
        counts = {
            "round": RoundFiles(
                files_imported=len(wrote),
                files_imported_before=len(answers) - len(wrote) - len(left),
                not_imported=tuple(left),
            ).model_dump(mode="json")
        }
        try:
            if not wrote:
                return {**ImportedBefore().model_dump(mode="json"), **counts}
            progress.advance(CHECKING_PERCENT, CHECKING_MESSAGE)
            summed = _summed(wrote)
            reports = self._reports(summed, _imported(len(wrote), len(files), left))
            return {**summed.model_dump(mode="json"), "reports": reports, **counts}
        finally:
            for upload_id, answer in answered:
                if not isinstance(answer, NotImported):
                    self._upload_removed(upload_id)

    def _reports(self, wrote: ImportWrote, imported: str) -> list[dict[str, Any]]:
        """The quality report of each provider's data of each root `wrote` wrote, and the
        profiles indexed where the import kept one; a failure here says `imported`."""
        products = sorted({(each.dataset.provider, each.dataset.root) for each in wrote.datasets})
        paths = self.paths
        try:
            reports = [
                written_report(self.store, paths.reports_dir, paths.cache_dir, provider, root)
                for provider, root in products
            ]
            if wrote.profile_kept:
                tried_while_busy(self.index_profiles)
        except Exception as failure:
            raise ExecutionFailedError(
                f"{imported}, {REPORT_FAILED}: "
                f"{type(failure).__name__}: {failure}. Check quality on its dataset's page "
                "writes the report again."
            ) from failure
        return reports

    def _upload_removed(self, upload_id: UUID | None) -> None:
        if upload_id is not None:
            self.uploads.remove(upload_id)


@dataclass
class _Stages:
    """An import's reports as the job's progress, which remember whether it writes."""

    progress: JobProgress
    writing: bool = False

    def imported(self, executor: Executor, spec: ImportSpec) -> ImportAnswer:
        """What the runner answered; a failure or a timeout once the import writes says so."""
        try:
            return _answer(executor, spec, self.report, self.progress.check)
        except ExecutionFailedError as failed:
            raise ExecutionFailedError(_said(str(failed), self.writing)) from failed
        except ExecutionTimedOutError as timed_out:
            raise ExecutionTimedOutError(_said(str(timed_out), self.writing)) from timed_out

    def report(self, reported: ExecutionProgress) -> None:
        """The runner's report as the job's progress; the first that says the import writes
        takes the job past stopping (module docstring)."""
        if self.writing or reported.percent < WRITING_PERCENT:
            advancing(self.progress)(reported)
            return
        self.progress.advance_past_stopping(reported.percent, reported.message)
        self.writing = True


@dataclass
class _Round:
    """A round's progress over its `files` (module docstring), which remembers how many are
    done, whether the file it imports writes, and whether one has: a runner's first report that
    its file writes is said as that file's, its others left out."""

    progress: JobProgress
    files: int
    done: int = 0
    writing: bool = False
    wrote: bool = False

    def imported(self, executor: Executor, spec: ImportSpec, upload_id: UUID | None) -> FileAnswer:
        """What the round's next file, `spec`'s, gave: a refusal, or a failure, a timeout, or a
        refused start of its runner, leaves it out with why, which keeps its start and says whether
        the file stopped while it wrote."""
        self.writing = False
        self.progress.advance(self._percent(), f"Reading {self._file()}")
        try:
            answer = _answer(executor, spec, self.report, self.progress.check)
        except (ExecutionFailedError, ExecutionTimedOutError, OSError) as failed:
            answer = RefusedImport(message=_last_line(str(failed)))
        self.done += 1
        if not isinstance(answer, RefusedImport):
            return answer
        return NotImported(
            upload_id=upload_id,
            file_name=spec.request.path.name,
            message=_said(answer.message[:LINE_CHARS], self.writing)[:LINE_CHARS],
        )

    def report(self, reported: ExecutionProgress) -> None:
        """The runner's first report that its file writes as the round's, past stopping where
        no file wrote before it; the runner's other reports left out."""
        if self.writing or reported.percent < WRITING_PERCENT:
            return
        self.writing = True
        message = f"Writing {self._file()}"
        if self.wrote:
            self.progress.advance(self._percent(), message)
            return
        self.wrote = True
        self.progress.advance_past_stopping(self._percent(), message)

    def _percent(self) -> float:
        """The round's progress by the files done: up to `WRITING_PERCENT` until a file writes,
        then on from it to `CHECKING_PERCENT`."""
        if not self.wrote:
            return WRITING_PERCENT * self.done / self.files
        return WRITING_PERCENT + (CHECKING_PERCENT - WRITING_PERCENT) * self.done / self.files

    def _file(self) -> str:
        return "the file" if self.files == 1 else f"file {self.done + 1} of {self.files}"


def _answer(
    executor: Executor, spec: ImportSpec, report: ProgressReport, check: StopCheck
) -> ImportAnswer:
    """What the runner answered of `spec`'s import."""
    output = executed(executor, spec, report, check).output
    if not isinstance(output, ImportOutput):
        raise ValueError(f"Expected the output of an import, got that of a {output.kind}.")
    return output.answer


def _imported(wrote: int, files: int, left: list[NotImported]) -> str:
    """How many of a round's `files` were imported, and which were left out, for the error of
    reports that failed, since a failed job gives no result."""
    if files == 1:
        return "The file was imported"
    imported = f"{wrote} of the {files} files were imported"
    if not left:
        return imported
    return f"{imported} and {len(left)} left out, the first {left[0].file_name}"


def _none_imported(left: list[NotImported], files: int) -> str:
    """Why a round that wrote nothing failed: the file that stopped while it wrote, which
    importing it again finishes, else the first file left out."""
    stopped = [each for each in left if each.message.startswith(STOPPED_WHILE_WRITING)]
    named = (stopped or left)[0]
    return (
        f"Expected a file imported, got {len(left)} of the {files} files not imported. "
        f"{named.file_name}: {named.message}"
    )


def _said(message: str, writing: bool) -> str:
    """`message`, after what an import that stopped while it `writing` leaves, its end kept
    where the two would run past a job's error."""
    if not writing:
        return message
    return f"{STOPPED_WHILE_WRITING}{message[len(STOPPED_WHILE_WRITING) - ERROR_CHARS :]}"


def _last_line(error: str) -> str:
    """The last line of a runner's error, which names its exception."""
    lines = error.strip().splitlines()
    return lines[-1] if lines else "the runner gave no error"


def _summed(wrote: list[ImportWrote]) -> ImportWrote:
    """What a round's files wrote, as one import: each dataset's account added up, since each
    file counted against the store as the files before it left it; the instrument saved and the
    profile kept where a file's import did; and the first refusal to keep it."""
    accounts: dict[Dataset, list[DatasetWritten]] = {}
    for each in wrote:
        for account in each.datasets:
            accounts.setdefault(account.dataset, []).append(account)
    refusals = [each.profile_refusal for each in wrote if each.profile_refusal is not None]
    return ImportWrote(
        datasets=tuple(_added_up(dataset, written) for dataset, written in accounts.items()),
        instrument_saved=any(each.instrument_saved for each in wrote),
        profile_kept=any(each.profile_kept for each in wrote),
        profile_refusal=refusals[0] if refusals else None,
    )


def _added_up(dataset: Dataset, written: list[DatasetWritten]) -> DatasetWritten:
    return DatasetWritten(
        dataset=dataset,
        records_added=sum(each.records_added for each in written),
        records_held=sum(each.records_held for each in written),
        records_taken=sum(each.records_taken for each in written),
        new_sessions=sum(each.new_sessions for each in written),
        records_left_out=sum(each.records_left_out for each in written),
    )
