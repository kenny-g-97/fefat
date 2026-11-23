"""An import as a job (step 5.12, `01-architecture.md` section 6), run in this process as the pool's
worker runs it: the import runs in the executor's runner, never in the worker's own process (Done
means 2), its stages reaching the job's stream before the quality report of what it wrote, and
its upload removed once that is written; a request to stop before the file is read stops it with
nothing written, while one once it writes is refused, by the API with 409, and one taken as it
begins to write is cleared, so that neither the worker nor the reaper ends an import that
writes; and a failure once the import wrote says the file was imported."""

import asyncio
import os
import shutil
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import fefat_app.jobs.imports as import_jobs
from export_samples import (
    PRESETS,
    SAMPLES,
    sample_lines,
    with_a_lot_more_in_the_last_bar,
    written_export,
)
from fefat.config import Settings, resolve_paths
from fefat.market.calendar_breaks import (
    BarsInBreaks,
    BreaksWithBars,
    BreakWithBars,
    SessionLeftOut,
)
from fefat.market.importers.partition_merge import DifferingRecords
from fefat.market.importers.profiles import keep_profile
from fefat.market.layout import Dataset
from fefat.market.schema import parse_schema_name
from fefat.market.store import Store
from fefat_app.container import Container
from fefat_app.database.job_records import JobTables
from fefat_app.execution import (
    ExecutionFailed,
    ExecutionProgress,
    ExecutionResult,
    ExecutionSpec,
    ExecutionSucceeded,
    ExecutionTimedOut,
    ProgressReport,
    StopCheck,
    keep_running,
)
from fefat_app.executor.imports import _breaks_seen, import_output
from fefat_app.executor.protocol import ERROR_CHARS
from fefat_app.executor.runner_process import leftovers_removed
from fefat_app.executor.subprocess_executor import SubprocessExecutor
from fefat_app.imports import (
    CHECKING_MESSAGE,
    CHECKING_PERCENT,
    LINE_CHARS,
    WRITING_MESSAGE,
    WRITING_PERCENT,
    BatchRequest,
    DatasetWritten,
    FileRequest,
    ImportedBefore,
    ImportJobPayload,
    ImportOutput,
    ImportSpec,
    ImportWrote,
    NoSuchUploadError,
    PathRefusedError,
    RefusedImport,
    RoundFile,
)
from fefat_app.job_models import Job, JobKind, JobStatus, job_stream
from fefat_app.jobs.catalog_sync import written_report
from fefat_app.jobs.executions import ExecutionFailedError
from fefat_app.jobs.imports import STOPPED_WHILE_WRITING, ImportJobs
from fefat_app.jobs.progress import JobCancelledError, JobProgress
from fefat_app.jobs.worker import JobTimings, run_job
from fefat_app.ports import Executor
from fefat_app.services.imports import IMPORT_LIMITS, Imports
from fefat_app.services.jobs import JobPastStoppingError, Jobs
from fefat_app.uploads import UploadFolders
from local_server import STARTED_AT, RecordingDispatcher, SettableClock, logged_in
from test_http_imports import refused_in_this_process

WORKER = 4242
NINJATRADER_SAMPLE = SAMPLES["ninjatrader"][0]
TEN_BARS_WRITTEN = ImportWrote(
    datasets=(
        DatasetWritten(
            dataset=Dataset.model_validate(
                {"provider": "ninjatrader", "schema_name": "ohlcv-1m", "root": "ES"}
            ),
            records_added=10,
            records_held=0,
            records_taken=0,
            new_sessions=1,
        ),
    ),
    instrument_saved=False,
    profile_kept=False,
    profile_refusal=None,
)
"""What a fake runner writes of each file it imports."""


def an_import(
    job_records: JobTables,
    path: Path,
    upload_id: UUID | None = None,
    time_zone: str | None = None,
    others: tuple[RoundFile, ...] = (),
    in_round: bool = False,
) -> Job:
    """A queued `import` job of the file `path` with the NinjaTrader preset, read in
    `time_zone` where one is given, and, `in_round`, of the `others` in the same round."""
    request = FileRequest(
        path=path,
        profile=PRESETS["ninjatrader"],
        keep_profile=False,
        contract=None,
        root=None,
        time_zone=time_zone,
        differing=DifferingRecords.REFUSE,
    )
    payload = ImportJobPayload(
        spec=ImportSpec(request=request, limits=IMPORT_LIMITS),
        upload_id=upload_id,
        others=others,
        in_round=in_round,
    )
    return job_records.add(JobKind.IMPORT, payload.model_dump(mode="json"), 3, STARTED_AT)


def a_round(job_records: JobTables, *exports: Path) -> tuple[Job, list[UUID]]:
    """A queued `import` job of `exports`, each kept as an upload, in one round (D-102), and
    the uploads' ids."""
    uploads_dir = resolve_paths(os.environ).uploads_dir
    kept = [kept_upload(export) for export in exports]
    first, *others = (
        RoundFile(path=uploads_dir / str(upload) / export.name, upload_id=upload)
        for export, upload in zip(exports, kept, strict=True)
    )
    job = an_import(job_records, first.path, first.upload_id, others=tuple(others), in_round=True)
    return job, kept


def started(job_records: JobTables, job: Job) -> Job:
    held = job_records.start(job.id, WORKER, STARTED_AT + timedelta(hours=1), STARTED_AT)
    assert held is not None
    return held


def the_import_jobs(executor: Executor) -> ImportJobs:
    paths = resolve_paths(os.environ)
    uploads = UploadFolders(paths.uploads_dir, SettableClock(STARTED_AT))
    return ImportJobs(executor, Store(paths.data_dir), paths, lambda: 0, uploads)


def kept_upload(path: Path) -> UUID:
    """The id of `path` kept as an upload, as the route keeps one."""

    async def chunks() -> AsyncIterator[bytes]:
        yield path.read_bytes()

    uploads = UploadFolders(resolve_paths(os.environ).uploads_dir, SettableClock(STARTED_AT))
    return asyncio.run(uploads.keep(path.name, chunks())).id


def test_an_import_job_runs_its_import_in_the_runner_and_reports_its_stages(
    job_records: JobTables, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Done means 2: the worker's own process holds every importer refusing, and the job still
    # imports, its stages in order, then removes its upload.
    refused_in_this_process(monkeypatch)
    upload_id = kept_upload(NINJATRADER_SAMPLE)
    paths = resolve_paths(os.environ)
    job = an_import(
        job_records, paths.uploads_dir / str(upload_id) / NINJATRADER_SAMPLE.name, upload_id
    )

    run_job(job.id, paths, JobTimings())

    ended = job_records.by_id(job.id)
    assert ended is not None
    assert ended.status == JobStatus.SUCCEEDED, ended.error
    events = job_records.events_after(job_stream(job.id), 0, 100)
    assert [(each.said.get("status"), each.said.get("percent")) for each in events] == [
        ("queued", None),
        ("running", None),
        (None, 0.0),
        (None, WRITING_PERCENT),
        (None, 80.0),
        ("succeeded", None),
    ]
    assert ended.result is not None
    assert ended.result["kind"] == "wrote"
    assert [report["root"] for report in ended.result["reports"]] == ["ES"]
    assert Store(paths.data_dir).list_datasets() != ()
    assert not (paths.uploads_dir / str(upload_id)).exists()


def test_an_import_asked_to_stop_before_its_file_is_read_stops_with_nothing_written(
    job_records: JobTables, executor: SubprocessExecutor
) -> None:
    job = started(job_records, an_import(job_records, NINJATRADER_SAMPLE))
    job_records.request_cancel(job.id, STARTED_AT, stoppable_below=WRITING_PERCENT)

    with pytest.raises(JobCancelledError):
        the_import_jobs(executor).run(job.payload, JobProgress(job_records, job.id, WORKER))

    assert not resolve_paths(os.environ).data_dir.exists()


def test_an_import_that_writes_is_not_asked_to_stop_so_the_reaper_never_ends_it(
    job_records: JobTables, clock: SettableClock
) -> None:
    # Plan call 5: once an import writes, only running it again could finish one stopped.
    jobs = Jobs(job_records, RecordingDispatcher(), clock)
    reading = started(job_records, an_import(job_records, NINJATRADER_SAMPLE))
    writing = started(job_records, an_import(job_records, NINJATRADER_SAMPLE))
    job_records.advance(writing.id, WORKER, WRITING_PERCENT, "Writing the partitions", {})

    asked = jobs.cancel(reading.id)
    with pytest.raises(JobPastStoppingError, match="runs to its end once it writes"):
        jobs.cancel(writing.id)
    late = job_records.request_cancel(writing.id, clock(), stoppable_below=WRITING_PERCENT)

    assert asked.cancel_requested_at == clock()
    assert late is None
    still = job_records.by_id(writing.id)
    assert still is not None
    assert (still.status, still.cancel_requested_at) == (JobStatus.RUNNING, None)


def test_the_api_refuses_to_stop_an_import_that_writes_with_409(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    csrf = logged_in(client, container)
    writing = started(job_records, an_import(job_records, NINJATRADER_SAMPLE))
    job_records.advance(writing.id, WORKER, WRITING_PERCENT, "Writing the partitions", {})

    response = client.post(f"/v1/jobs/{writing.id}/cancel", headers=csrf)

    assert response.status_code == 409
    assert "importing its file again" in response.json()["detail"]


@dataclass(frozen=True)
class AskedToStopAsItWrites:
    """A runner whose import is asked to stop in the moment before it reports that it writes, as
    a request the server took in the last second of the read reaches the worker, then reports
    on and answers `answer`, or fails with `error`."""

    job_records: JobTables
    job_id: str
    error: str | None = None

    def run(
        self, spec: ExecutionSpec, report: ProgressReport, check: StopCheck = keep_running
    ) -> ExecutionResult:
        self.job_records.request_cancel(self.job_id, STARTED_AT, stoppable_below=WRITING_PERCENT)
        report(ExecutionProgress(percent=WRITING_PERCENT, message="Writing", details={}))
        check()
        if self.error is not None:
            return ExecutionFailed(error=self.error, stdout_tail="")
        report(ExecutionProgress(percent=CHECKING_PERCENT, message="Checking", details={}))
        return ExecutionSucceeded(output=ImportOutput(answer=ImportedBefore()))

    def close(self) -> None:
        """Keeps no process."""


@dataclass(frozen=True)
class AskedToStopWhileItReads:
    """A runner whose import is asked to stop while it reads, the worker's check of each
    second without a report then called."""

    job_records: JobTables
    job_id: str

    def run(
        self, spec: ExecutionSpec, report: ProgressReport, check: StopCheck = keep_running
    ) -> ExecutionResult:
        self.job_records.request_cancel(self.job_id, STARTED_AT, stoppable_below=WRITING_PERCENT)
        check()
        raise AssertionError("Expected the worker's check to stop the runner while it reads.")

    def close(self) -> None:
        """Keeps no process."""


def test_a_request_to_stop_taken_as_the_import_begins_to_write_is_cleared_and_never_stops_it(
    job_records: JobTables,
) -> None:
    # From the reviews: a request the server took below 40 % reached the worker at the report
    # that the import writes, and stopped the runner as it wrote; that report now clears it.
    job = started(job_records, an_import(job_records, NINJATRADER_SAMPLE))

    result = the_import_jobs(AskedToStopAsItWrites(job_records, job.id)).run(
        job.payload, JobProgress(job_records, job.id, WORKER)
    )

    assert result == {"kind": "imported_before"}
    still = job_records.by_id(job.id)
    assert still is not None
    assert (still.progress, still.cancel_requested_at) == (CHECKING_PERCENT, None)


def test_an_import_asked_to_stop_while_its_runner_reads_is_stopped_by_the_workers_check(
    job_records: JobTables,
) -> None:
    job = started(job_records, an_import(job_records, NINJATRADER_SAMPLE))

    with pytest.raises(JobCancelledError, match="asked to stop"):
        the_import_jobs(AskedToStopWhileItReads(job_records, job.id)).run(
            job.payload, JobProgress(job_records, job.id, WORKER)
        )


def test_a_failure_once_the_import_wrote_keeps_the_end_of_its_error_within_a_jobs(
    job_records: JobTables,
) -> None:
    # From the reviews: the worker kept a job's error's first 4,000 characters, so the line that
    # names the exception went once the import's prefix stood before a long traceback.
    job = started(job_records, an_import(job_records, NINJATRADER_SAMPLE))
    traceback = "x" * ERROR_CHARS + "\nValueError: the partition is gone"

    with pytest.raises(ExecutionFailedError) as failed:
        the_import_jobs(AskedToStopAsItWrites(job_records, job.id, traceback)).run(
            job.payload, JobProgress(job_records, job.id, WORKER)
        )

    said = str(failed.value)
    assert said.startswith(STOPPED_WHILE_WRITING)
    assert said.endswith("ValueError: the partition is gone")
    assert len(said) <= ERROR_CHARS


def test_an_imports_upload_is_removed_after_its_reports_and_kept_where_it_is_refused(
    job_records: JobTables,
    executor: SubprocessExecutor,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # From the reviews: an import stopped while it wrote its reports was queued again without
    # its file; a refused import keeps its upload, for the trader to import it again.
    paths = resolve_paths(os.environ)
    revised = written_export(
        tmp_path / "revised",
        NINJATRADER_SAMPLE.name,
        with_a_lot_more_in_the_last_bar(sample_lines("ninjatrader")),
    )
    kept, refused = kept_upload(NINJATRADER_SAMPLE), kept_upload(revised)
    present: list[bool] = []

    def reporting(*arguments: Any) -> dict[str, Any]:
        present.append((paths.uploads_dir / str(kept)).exists())
        return written_report(*arguments)

    monkeypatch.setattr(import_jobs, "written_report", reporting)
    job = started(
        job_records,
        an_import(job_records, paths.uploads_dir / str(kept) / NINJATRADER_SAMPLE.name, kept),
    )
    late = started(
        job_records,
        an_import(
            job_records,
            paths.uploads_dir / str(refused) / NINJATRADER_SAMPLE.name,
            refused,
            time_zone="America/Chicago",
        ),
    )

    the_import_jobs(executor).run(job.payload, JobProgress(job_records, job.id, WORKER))
    with pytest.raises(ExecutionFailedError, match="6 hours late"):
        the_import_jobs(executor).run(late.payload, JobProgress(job_records, late.id, WORKER))

    assert present == [True]
    assert not (paths.uploads_dir / str(kept)).exists()
    assert (paths.uploads_dir / str(refused)).exists()


def test_fefat_up_keeps_the_uploads_of_imports_still_queued(
    job_records: JobTables, container: Container
) -> None:
    # From the reviews: `fefat up` removed uploads left a day before the reaper queued their
    # imports again, which then failed without their files.
    paths = resolve_paths(os.environ)
    queued, left = kept_upload(NINJATRADER_SAMPLE), kept_upload(NINJATRADER_SAMPLE)
    an_import(job_records, paths.uploads_dir / str(queued) / NINJATRADER_SAMPLE.name, queued)
    two_days_ago = time.time() - 2 * 24 * 3600
    for upload in (queued, left):
        os.utime(paths.uploads_dir / str(upload), (two_days_ago, two_days_ago))

    leftovers_removed(paths.uploads_dir, container.imports.uploads_of_active_imports())

    assert sorted(path.name for path in paths.uploads_dir.iterdir()) == [str(queued)]


def test_a_broken_archive_is_refused_in_words_by_the_runner(tmp_path: Path) -> None:
    # From the reviews: a `.zip` that is none failed the import's job with a traceback.
    broken = tmp_path / "bars.csv.zip"
    broken.write_bytes(b"not an archive")
    request = FileRequest(
        path=broken,
        profile=PRESETS["ninjatrader"],
        keep_profile=False,
        contract=None,
        root=None,
        time_zone=None,
        differing=DifferingRecords.REFUSE,
    )

    answer = import_output(ImportSpec(request=request, limits=IMPORT_LIMITS), lambda _: None)

    assert isinstance(answer.answer, RefusedImport)
    assert "zip" in answer.answer.message


def test_a_profile_not_kept_after_its_import_wrote_is_said_beside_the_records_imported() -> None:
    # From the reviews: another profile kept under the name meanwhile turned an import that
    # wrote into a refusal, its quality report and its upload's removal skipped.
    paths = resolve_paths(os.environ)
    mine = PRESETS["ninjatrader"].model_copy(update={"name": "mine"})
    keep_profile(mine.model_copy(update={"description": "Another"}), paths.profiles_dir)
    request = FileRequest(
        path=NINJATRADER_SAMPLE,
        profile=mine,
        keep_profile=True,
        contract=None,
        root=None,
        time_zone=None,
        differing=DifferingRecords.REFUSE,
    )

    answer = import_output(ImportSpec(request=request, limits=IMPORT_LIMITS), lambda _: None)

    assert isinstance(answer.answer, ImportWrote)
    assert answer.answer.profile_kept is False
    assert answer.answer.profile_refusal is not None
    assert "rename one of them" in answer.answer.profile_refusal
    assert Store(paths.data_dir).list_datasets() != ()


def test_a_report_that_fails_once_the_import_wrote_says_the_file_was_imported(
    job_records: JobTables, executor: SubprocessExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(*_: object) -> object:
        raise OSError("the reports' folder is gone")

    monkeypatch.setattr(import_jobs, "written_report", failing)
    job = started(job_records, an_import(job_records, NINJATRADER_SAMPLE))

    with pytest.raises(
        ExecutionFailedError, match="The file was imported, then its quality report"
    ):
        the_import_jobs(executor).run(job.payload, JobProgress(job_records, job.id, WORKER))

    assert Store(resolve_paths(os.environ).data_dir).list_datasets() != ()


@dataclass(frozen=True)
class AnswersEachFile:
    """A runner that answers each file of a round by its name: it writes those of `writes`,
    reporting its stages as the importer does; it fails once it writes for those of `fails`,
    and refuses them at length for those of `refuses_writing`; it runs out of time for those of
    `times_out`, and cannot start for those of `cannot_start`; and it refuses the others before
    it reads them."""

    writes: tuple[str, ...] = ()
    fails: tuple[str, ...] = ()
    refuses_writing: tuple[str, ...] = ()
    times_out: tuple[str, ...] = ()
    cannot_start: tuple[str, ...] = ()

    def run(
        self, spec: ExecutionSpec, report: ProgressReport, check: StopCheck = keep_running
    ) -> ExecutionResult:
        assert isinstance(spec, ImportSpec)
        name = spec.request.path.name
        if name in self.cannot_start:
            raise OSError("[Errno 28] No space left on device")
        if name in self.times_out:
            return ExecutionTimedOut()
        if name not in (*self.writes, *self.fails, *self.refuses_writing):
            refused = RefusedImport(message=f"Expected the contract of the records of {name}.")
            return ExecutionSucceeded(output=ImportOutput(answer=refused))
        report(ExecutionProgress(percent=WRITING_PERCENT, message=WRITING_MESSAGE, details={}))
        if name in self.fails:
            error = "Traceback (most recent call last):\nOSError: the disk is full"
            return ExecutionFailed(error=error, stdout_tail="")
        if name in self.refuses_writing:
            refused = RefusedImport(message="Expected the partitions written, got " + "x" * 4000)
            return ExecutionSucceeded(output=ImportOutput(answer=refused))
        report(ExecutionProgress(percent=CHECKING_PERCENT, message=CHECKING_MESSAGE, details={}))
        return ExecutionSucceeded(output=ImportOutput(answer=TEN_BARS_WRITTEN))

    def close(self) -> None:
        """Keeps no process."""


@dataclass(frozen=True)
class AskedToStopAsTheFirstIsRefused:
    """A runner that refuses each file it is given, recorded in `given`, the round asked to stop
    as it refuses the first."""

    job_records: JobTables
    job_id: str
    given: list[str]

    def run(
        self, spec: ExecutionSpec, report: ProgressReport, check: StopCheck = keep_running
    ) -> ExecutionResult:
        assert isinstance(spec, ImportSpec)
        self.given.append(spec.request.path.name)
        self.job_records.request_cancel(self.job_id, STARTED_AT, stoppable_below=WRITING_PERCENT)
        refused = RefusedImport(message="Expected the contract of the records.")
        return ExecutionSucceeded(output=ImportOutput(answer=refused))

    def close(self) -> None:
        """Keeps no process."""


def reports_recorded(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """The products whose quality report an import job writes, each recorded in place of its
    report."""
    recorded: list[tuple[str, str]] = []

    def recording(
        store: Store, reports_dir: Path, cache_dir: Path, provider: str, root: str
    ) -> dict[str, Any]:
        recorded.append((provider, root))
        return {"provider": provider, "root": root}

    monkeypatch.setattr(import_jobs, "written_report", recording)
    return recorded


def exports(folder: Path, *names: str) -> list[Path]:
    """The sample's lines written as an export under each of `names`."""
    return [written_export(folder, name, sample_lines("ninjatrader")) for name in names]


def test_a_round_reads_and_writes_its_files_in_turn_then_checks_their_quality_once(
    job_records: JobTables, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # D-102: until a file writes, the files read take the round to 40 %, then the files done to
    # 80 %, each runner's later stages left out; the reports are written once, at its end.
    checked = reports_recorded(monkeypatch)
    march, june = exports(tmp_path, "ES 03-26.Last.txt", "ES 06-26.Last.txt")
    queued, _ = a_round(job_records, march, june)
    job = started(job_records, queued)

    result = the_import_jobs(AnswersEachFile(writes=(march.name, june.name))).run(
        job.payload, JobProgress(job_records, job.id, WORKER)
    )

    events = job_records.events_after(job_stream(job.id), 0, 100)
    assert [(each.said["percent"], each.said["message"]) for each in events[2:]] == [
        (0.0, "Reading file 1 of 2"),
        (WRITING_PERCENT, "Writing file 1 of 2"),
        (60.0, "Reading file 2 of 2"),
        (60.0, "Writing file 2 of 2"),
        (CHECKING_PERCENT, CHECKING_MESSAGE),
    ]
    (written,) = result["datasets"]
    assert written["records_added"] == 20
    assert result["round"] == {
        "files_imported": 2,
        "files_imported_before": 0,
        "not_imported": [],
    }
    assert checked == [("ninjatrader", "ES")]


def test_a_round_asked_to_stop_between_two_files_before_one_writes_stops_there(
    job_records: JobTables, tmp_path: Path
) -> None:
    # D-102: until a file of the round writes, a request to stop stops it between two files.
    march, june = exports(tmp_path, "ES 03-26.Last.txt", "ES 06-26.Last.txt")
    queued, uploads = a_round(job_records, march, june)
    job = started(job_records, queued)
    given: list[str] = []

    with pytest.raises(JobCancelledError, match="asked to stop"):
        the_import_jobs(AskedToStopAsTheFirstIsRefused(job_records, job.id, given)).run(
            job.payload, JobProgress(job_records, job.id, WORKER)
        )

    assert given == [march.name]
    uploads_dir = resolve_paths(os.environ).uploads_dir
    assert all((uploads_dir / str(upload)).exists() for upload in uploads)


def test_a_file_the_round_could_not_import_is_left_out_with_why_and_keeps_its_upload(
    job_records: JobTables, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # D-102: a file refused, or whose runner fails, takes no other with it; only a file that
    # wrote is said to have stopped while it wrote, and only the files imported lose their
    # uploads.
    reports_recorded(monkeypatch)
    march, june, unnamed, september = exports(
        tmp_path, "ES 03-26.Last.txt", "ES 06-26.Last.txt", "bars.txt", "ES 09-26.Last.txt"
    )
    queued, uploads = a_round(job_records, march, june, unnamed, september)
    job = started(job_records, queued)
    runner = AnswersEachFile(writes=(march.name, september.name), fails=(june.name,))

    result = the_import_jobs(runner).run(job.payload, JobProgress(job_records, job.id, WORKER))

    assert (result["round"]["files_imported"], len(result["round"]["not_imported"])) == (2, 2)
    assert result["datasets"][0]["records_added"] == 20
    failed, refused = result["round"]["not_imported"]
    assert (failed["upload_id"], failed["file_name"]) == (str(uploads[1]), june.name)
    assert failed["message"].startswith(STOPPED_WHILE_WRITING)
    assert failed["message"].endswith("OSError: the disk is full")
    assert (refused["upload_id"], refused["file_name"]) == (str(uploads[2]), unnamed.name)
    assert refused["message"] == "Expected the contract of the records of bars.txt."
    uploads_dir = resolve_paths(os.environ).uploads_dir
    assert [(uploads_dir / str(upload)).exists() for upload in uploads] == [
        False,
        True,
        True,
        False,
    ]


def test_a_round_of_which_no_file_was_imported_fails_with_the_first_reason_and_keeps_uploads(
    job_records: JobTables, tmp_path: Path
) -> None:
    # D-102: a round that imported nothing fails as one file's import does, its files kept for
    # another round.
    unnamed, other = exports(tmp_path, "bars.txt", "more bars.txt")
    queued, uploads = a_round(job_records, unnamed, other)
    job = started(job_records, queued)

    with pytest.raises(ExecutionFailedError) as failed:
        the_import_jobs(AnswersEachFile()).run(
            job.payload, JobProgress(job_records, job.id, WORKER)
        )

    said = str(failed.value)
    assert "2 of the 2 files not imported" in said
    assert said.endswith("bars.txt: Expected the contract of the records of bars.txt.")
    uploads_dir = resolve_paths(os.environ).uploads_dir
    assert all((uploads_dir / str(upload)).exists() for upload in uploads)


def test_fefat_up_keeps_the_uploads_of_every_file_of_a_queued_round(
    job_records: JobTables, container: Container, tmp_path: Path
) -> None:
    # D-102: the uploads of a round's other files are its too.
    paths = resolve_paths(os.environ)
    _, kept = a_round(job_records, *exports(tmp_path, "ES 03-26.Last.txt", "ES 06-26.Last.txt"))
    left = kept_upload(NINJATRADER_SAMPLE)
    two_days_ago = time.time() - 2 * 24 * 3600
    for upload in (*kept, left):
        os.utime(paths.uploads_dir / str(upload), (two_days_ago, two_days_ago))

    leftovers_removed(paths.uploads_dir, container.imports.uploads_of_active_imports())

    assert sorted(path.name for path in paths.uploads_dir.iterdir()) == sorted(map(str, kept))


def test_a_rounds_first_write_clears_a_request_to_stop_taken_as_it_begins(
    job_records: JobTables, tmp_path: Path
) -> None:
    # From the reviews: as for one file, a request the server took below 40 % reaches the worker
    # at the report that the round's first file writes, which clears it rather than stopping the
    # runner as it writes.
    queued, _ = a_round(job_records, *exports(tmp_path, "ES 03-26.Last.txt", "ES 06-26.Last.txt"))
    job = started(job_records, queued)

    result = the_import_jobs(AskedToStopAsItWrites(job_records, job.id)).run(
        job.payload, JobProgress(job_records, job.id, WORKER)
    )

    assert (result["kind"], result["round"]["files_imported_before"]) == ("imported_before", 2)
    still = job_records.by_id(job.id)
    assert still is not None
    assert still.cancel_requested_at is None


def test_a_file_whose_runner_runs_out_of_time_or_cannot_start_is_left_out_with_why(
    job_records: JobTables, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # From the reviews: a file whose runner ran out of time, or could not start, as on a full
    # disk once other files wrote, is left out as a failed one is; and a long refusal of a file
    # that wrote keeps its start, which says what was expected, after what a stop leaves.
    reports_recorded(monkeypatch)
    march, june, september, december = exports(
        tmp_path, "ES 03-26.Last.txt", "ES 06-26.Last.txt", "ES 09-26.Last.txt", "ES 12-26.Last.txt"
    )
    queued, _ = a_round(job_records, march, june, september, december)
    job = started(job_records, queued)
    runner = AnswersEachFile(
        writes=(march.name,),
        times_out=(june.name,),
        cannot_start=(september.name,),
        refuses_writing=(december.name,),
    )

    result = the_import_jobs(runner).run(job.payload, JobProgress(job_records, job.id, WORKER))

    timed_out, unstarted, refused = (each["message"] for each in result["round"]["not_imported"])
    assert timed_out.startswith("This job ran past its limit of")
    assert unstarted.endswith("No space left on device")
    assert refused.startswith(f"{STOPPED_WHILE_WRITING}Expected the partitions written")
    assert len(refused) == LINE_CHARS


def test_a_round_of_which_no_file_was_imported_names_a_file_that_stopped_while_it_wrote(
    job_records: JobTables, tmp_path: Path
) -> None:
    # From the reviews: a file that stopped while it wrote, which importing it again finishes,
    # is the one the failed round names, though another was left out before it.
    unnamed, june = exports(tmp_path, "bars.txt", "ES 06-26.Last.txt")
    queued, _ = a_round(job_records, unnamed, june)
    job = started(job_records, queued)

    with pytest.raises(ExecutionFailedError) as failed:
        the_import_jobs(AnswersEachFile(fails=(june.name,))).run(
            job.payload, JobProgress(job_records, job.id, WORKER)
        )

    assert f"{june.name}: {STOPPED_WHILE_WRITING}" in str(failed.value)


def test_a_report_that_fails_after_a_round_says_how_many_files_were_imported(
    job_records: JobTables, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # From the reviews: a failed job has no result, so its error gives the round's account.
    def failing(*_: object) -> object:
        raise OSError("the reports' folder is gone")

    monkeypatch.setattr(import_jobs, "written_report", failing)
    march, unnamed = exports(tmp_path, "ES 03-26.Last.txt", "bars.txt")
    queued, _ = a_round(job_records, march, unnamed)
    job = started(job_records, queued)

    with pytest.raises(
        ExecutionFailedError,
        match=(
            r"1 of the 2 files were imported and 1 left out, the first bars\.txt, then its quality "
            "report failed"
        ),
    ):
        the_import_jobs(AnswersEachFile(writes=(march.name,))).run(
            job.payload, JobProgress(job_records, job.id, WORKER)
        )


def test_other_files_are_refused_beside_one_import_and_a_round_beside_a_batch() -> None:
    # D-102: a payload's other files are a round's, and a round's files share one profile, which
    # a batch has none of.
    file = FileRequest(
        path=Path("ES 03-26.Last.txt"),
        profile=PRESETS["ninjatrader"],
        keep_profile=False,
        contract=None,
        root=None,
        time_zone=None,
        differing=DifferingRecords.REFUSE,
    )
    batch = BatchRequest(path=Path("batch"), differing=DifferingRecords.REFUSE)
    others = (RoundFile(path=Path("ES 06-26.Last.txt"), upload_id=None),)

    with pytest.raises(ValidationError, match="Expected the files of a round"):
        ImportJobPayload(
            spec=ImportSpec(request=file, limits=IMPORT_LIMITS), upload_id=None, others=others
        )
    with pytest.raises(ValidationError, match="Expected a round of files through a profile"):
        ImportJobPayload(
            spec=ImportSpec(request=batch, limits=IMPORT_LIMITS), upload_id=None, in_round=True
        )


def test_each_file_of_a_round_keeps_its_own_choice_for_its_bars_in_a_break() -> None:
    # Step 5.15: a round names the files the correction is approved for, and each file's import
    # carries its own choice, the first's in the spec and the others' beside their paths.
    file = FileRequest(
        path=Path("ES 03-26.Last.txt"),
        profile=PRESETS["ninjatrader"],
        keep_profile=False,
        contract=None,
        root=None,
        time_zone=None,
        differing=DifferingRecords.REFUSE,
        bars_in_breaks=BarsInBreaks.LEAVE_OUT,
    )
    others = (
        RoundFile(path=Path("ES 06-26.Last.txt"), upload_id=None),
        RoundFile(
            path=Path("ES 09-26.Last.txt"), upload_id=None, bars_in_breaks=BarsInBreaks.LEAVE_OUT
        ),
    )
    payload = ImportJobPayload(
        spec=ImportSpec(request=file, limits=IMPORT_LIMITS),
        upload_id=None,
        others=others,
        in_round=True,
    )

    chosen = [
        (spec.request.path.name, getattr(spec.request, "bars_in_breaks", None))
        for spec, _ in payload.files()
    ]

    assert chosen == [
        ("ES 03-26.Last.txt", BarsInBreaks.LEAVE_OUT),
        ("ES 06-26.Last.txt", BarsInBreaks.REFUSE),
        ("ES 09-26.Last.txt", BarsInBreaks.LEAVE_OUT),
    ]


def test_a_payload_queued_before_the_choice_refuses_bars_in_a_break(job_records: JobTables) -> None:
    # A job queued before step 5.15 has no choice in its payload, and reads as refusing them,
    # as every import did then.
    queued = an_import(job_records, Path("ES 03-26.Last.txt"))
    stored: dict[str, Any] = dict(queued.payload)
    request = {
        key: value for key, value in stored["spec"]["request"].items() if key != "bars_in_breaks"
    }
    stored["spec"] = {**stored["spec"], "request": request}

    payload = ImportJobPayload.model_validate(stored)

    assert isinstance(payload.spec.request, FileRequest)
    assert payload.spec.request.bars_in_breaks is BarsInBreaks.REFUSE


def a_finding(*ending: SessionLeftOut) -> BreaksWithBars:
    """A file's break after 02-04 with 60 bars, the sessions beside it, and `ending`, the
    sessions ending a bar early that go with them."""
    return BreaksWithBars(
        dataset=Dataset(
            provider="ninjatrader", schema_name=parse_schema_name("ohlcv-1m"), root="ES"
        ),
        breaks=(BreakWithBars(after=date(2026, 2, 4), bars=60),),
        sessions_beside=(
            SessionLeftOut(trade_date=date(2026, 2, 4), records=1_440),
            SessionLeftOut(trade_date=date(2026, 2, 5), records=1_380),
        ),
        sessions_ending_a_bar_early=ending,
    )


def test_a_reading_that_left_out_such_breaks_yet_holds_one_is_refused() -> None:
    # The step's review: the records the correction takes hold no bar in a break closing at the
    # next open, since the sessions beside every such break go with it (ADR-0022), so a reading
    # that says otherwise is a fault the runner refuses rather than words one way or the other.
    found = a_finding()

    with pytest.raises(ValueError, match="Expected no bar in a break closing at the next open"):
        _breaks_seen((found,), found)


def test_the_runner_names_the_sessions_ending_a_bar_early_and_counts_every_record_left_out() -> (
    None
):
    # The step's third review: the account the wizard words lists a session ending a bar early
    # apart from the sessions beside, and its records among those left out (D-104).
    seen = _breaks_seen(
        (a_finding(SessionLeftOut(trade_date=date(2026, 2, 3), records=1_379)),), None
    )

    assert seen is not None
    assert (seen.sessions, seen.ending_a_bar_early, seen.ending_a_bar_early_total) == (
        (date(2026, 2, 4), date(2026, 2, 5)),
        (date(2026, 2, 3),),
        1,
    )
    assert seen.records == 1_440 + 1_380 + 1_379


def test_a_round_of_one_file_counts_its_file(
    job_records: JobTables, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # From the reviews: of several files chosen, one may import as it is; its round still counts
    # its file, as the done card says.
    reports_recorded(monkeypatch)
    (march,) = exports(tmp_path, "ES 03-26.Last.txt")
    queued, _ = a_round(job_records, march)
    job = started(job_records, queued)

    result = the_import_jobs(AnswersEachFile(writes=(march.name,))).run(
        job.payload, JobProgress(job_records, job.id, WORKER)
    )

    assert result["round"] == {
        "files_imported": 1,
        "files_imported_before": 0,
        "not_imported": [],
    }


def imports_over(
    job_records: JobTables, roots: tuple[Path, ...]
) -> tuple[Imports, RecordingDispatcher]:
    """The imports over a dispatcher that runs nothing, with `roots` as the import roots."""
    paths = resolve_paths(os.environ)
    clock = SettableClock(STARTED_AT)
    dispatcher = RecordingDispatcher()
    imports = Imports(
        SubprocessExecutor(paths, warm_previews=False),
        Jobs(job_records, dispatcher, clock),
        UploadFolders(paths.uploads_dir, clock),
        paths,
        Settings(import_roots=roots),
    )
    return imports, dispatcher


def test_run_again_of_an_import_queues_its_files_once_while_they_are_kept(
    job_records: JobTables, tmp_path: Path
) -> None:
    # Step 5.19: a failed or cancelled import keeps its upload for this.
    imports, dispatcher = imports_over(job_records, ())
    march, june = exports(tmp_path, "ES 03-26.Last.txt", "ES 06-26.Last.txt")
    ended, _ = a_round(job_records, march, june)
    job_records.cancel_queued(ended.id, STARTED_AT)

    first = imports.start_again(ended)
    second = imports.start_again(ended)

    assert (first.kind, first.status, first.payload) == (
        JobKind.IMPORT,
        JobStatus.QUEUED,
        ended.payload,
    )
    assert second.id == first.id
    assert dispatcher.calls == [f"submit {first.id}"]


def test_run_again_of_an_import_whose_upload_is_gone_is_refused(
    job_records: JobTables, tmp_path: Path
) -> None:
    imports, dispatcher = imports_over(job_records, ())
    march, june = exports(tmp_path, "ES 03-26.Last.txt", "ES 06-26.Last.txt")
    ended, (_, removed) = a_round(job_records, march, june)
    job_records.cancel_queued(ended.id, STARTED_AT)
    shutil.rmtree(resolve_paths(os.environ).uploads_dir / str(removed))

    with pytest.raises(NoSuchUploadError, match="choose the file again"):
        imports.start_again(ended)

    assert dispatcher.calls == []


def test_run_again_of_a_path_the_import_roots_no_longer_hold_is_refused(
    job_records: JobTables, tmp_path: Path
) -> None:
    # A root taken out of config.toml since the import first ran no longer lets it be read.
    roots = tmp_path / "exports"
    roots.mkdir()
    (march,) = exports(roots, "ES 03-26.Last.txt")
    ended = an_import(job_records, march)
    job_records.cancel_queued(ended.id, STARTED_AT)
    allowed, dispatcher_allowed = imports_over(job_records, (roots,))
    refused, dispatcher_refused = imports_over(job_records, (tmp_path / "elsewhere",))

    with pytest.raises(PathRefusedError):
        refused.start_again(ended)
    again = allowed.start_again(ended)

    assert dispatcher_refused.calls == []
    assert dispatcher_allowed.calls == [f"submit {again.id}"]
