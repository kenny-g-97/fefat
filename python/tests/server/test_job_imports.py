"""An import as a job (step 5.12, `01-architecture.md` section 6), run in this process as the pool's
worker runs it: the import runs in the executor's runner, never in the worker's own process (Done
means 2), its stages reaching the job's stream before the quality report of what it wrote, and
its upload removed once it has written; a request to stop before the file is read stops it with
nothing written, while one once it writes is refused, by the API with 409, so that the reaper
never ends an import that writes; and a failure once the import wrote says the file was
imported."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import fefat_app.jobs.imports as import_jobs
from export_samples import PRESETS, SAMPLES
from fefat.config import resolve_paths
from fefat.market.importers.partition_merge import DifferingRecords
from fefat.market.store import Store
from fefat_app.container import Container
from fefat_app.database.job_records import JobTables
from fefat_app.executor.subprocess_executor import SubprocessExecutor
from fefat_app.imports import WRITING_PERCENT, FileRequest, ImportJobPayload, ImportSpec
from fefat_app.job_models import Job, JobKind, JobStatus, job_stream
from fefat_app.jobs.executions import ExecutionFailedError
from fefat_app.jobs.imports import ImportJobs
from fefat_app.jobs.progress import JobCancelledError, JobProgress
from fefat_app.jobs.worker import JobTimings, run_job
from fefat_app.services.imports import IMPORT_LIMITS
from fefat_app.services.jobs import JobPastStoppingError, Jobs
from fefat_app.uploads import UploadFolders
from local_server import STARTED_AT, RecordingDispatcher, SettableClock, logged_in
from test_http_imports import refused_in_this_process

WORKER = 4242
NINJATRADER_SAMPLE = SAMPLES["ninjatrader"][0]


def an_import(job_records: JobTables, path: Path, upload_id: UUID | None = None) -> Job:
    """A queued `import` job of the file `path` with the NinjaTrader preset."""
    request = FileRequest(
        path=path,
        profile=PRESETS["ninjatrader"],
        keep_profile=False,
        contract=None,
        root=None,
        time_zone=None,
        differing=DifferingRecords.REFUSE,
    )
    payload = ImportJobPayload(
        spec=ImportSpec(request=request, limits=IMPORT_LIMITS), upload_id=upload_id
    )
    return job_records.add(JobKind.IMPORT, payload.model_dump(mode="json"), 3, STARTED_AT)


def started(job_records: JobTables, job: Job) -> Job:
    held = job_records.start(job.id, WORKER, STARTED_AT + timedelta(hours=1), STARTED_AT)
    assert held is not None
    return held


def the_import_jobs(executor: SubprocessExecutor) -> ImportJobs:
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
