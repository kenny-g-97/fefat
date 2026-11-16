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
The result holds counts alone, since every job's is listed with the jobs."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fefat.config import FefatPaths
from fefat.market.store import Store
from fefat_app.execution import ExecutionProgress
from fefat_app.executor.protocol import ERROR_CHARS
from fefat_app.imports import (
    WRITING_PERCENT,
    ImportedBefore,
    ImportJobPayload,
    ImportOutput,
    ImportWrote,
    RefusedImport,
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
        progress.advance(0, READING_MESSAGE)
        following = _Stages(progress)
        answer = following.imported(self.executor, job)
        if isinstance(answer, RefusedImport):
            raise ExecutionFailedError(following.said(answer.message))
        try:
            if isinstance(answer, ImportedBefore):
                return answer.model_dump(mode="json")
            return {**answer.model_dump(mode="json"), "reports": self._reports(answer)}
        finally:
            self._upload_removed(job.upload_id)

    def _reports(self, wrote: ImportWrote) -> list[dict[str, Any]]:
        """The quality report of each provider's data of each root `wrote` wrote, and the
        profiles indexed where the import kept one; a failure here says the file was imported."""
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
                f"The file was imported, then its quality report failed: "
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

    def imported(
        self, executor: Executor, job: ImportJobPayload
    ) -> ImportWrote | ImportedBefore | RefusedImport:
        """What the runner answered; a failure or a timeout once the import writes says so."""
        try:
            output = executed(executor, job.spec, self.report, self.progress.check).output
        except ExecutionFailedError as failed:
            raise ExecutionFailedError(self.said(str(failed))) from failed
        except ExecutionTimedOutError as timed_out:
            raise ExecutionTimedOutError(self.said(str(timed_out))) from timed_out
        if not isinstance(output, ImportOutput):
            raise ValueError(f"Expected the output of an import, got that of a {output.kind}.")
        return output.answer

    def report(self, reported: ExecutionProgress) -> None:
        """The runner's report as the job's progress; the first that says the import writes
        takes the job past stopping (module docstring)."""
        if self.writing or reported.percent < WRITING_PERCENT:
            advancing(self.progress)(reported)
            return
        self.progress.advance_past_stopping(reported.percent, reported.message)
        self.writing = True

    def said(self, message: str) -> str:
        """`message`, after what an import that stopped while it wrote leaves, its end kept
        where the two would run past a job's error."""
        if not self.writing:
            return message
        return f"{STOPPED_WHILE_WRITING}{message[len(STOPPED_WHILE_WRITING) - ERROR_CHARS :]}"
