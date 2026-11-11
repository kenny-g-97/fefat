"""The catalog sync of step 5.1 (D-93, `01-architecture.md` section 6): the quality report of a
product, or of every product the store holds, written by a worker as `fefat data quality` writes
it, run here in the test's own process as `test_job_worker` runs the demo. Done means 3: a sync
run twice gives the same reports and lists each dataset once."""

import os

import polars as pl
from fastapi.testclient import TestClient
from polars.testing import assert_frame_equal

from fefat.config import resolve_paths
from fefat.market.quality_report import DAYS_FILE_NAME, FINDINGS_FILE_NAME, MARKDOWN_FILE_NAME
from fefat_app.container import Container
from fefat_app.database.job_records import JobTables
from fefat_app.job_models import Job, JobEventType, JobKind, JobStatus, job_stream
from fefat_app.jobs.worker import JobTimings, run_job
from local_server import STARTED_AT, logged_in
from notebook_runs import store_with

MINUTE = 60_000_000_000
SIX_DATASETS = [
    f"synthetic:{schema}:{root}"
    for root in ("BTCUSDT-PERP", "ES")
    for schema in ("ohlcv-1m", "ohlcv-1s", "trades")
]
CLEAN = {"provider": "synthetic", "status": "clean", "findings": 0}


def synced(job_records: JobTables, root: str | None) -> Job:
    """A catalog sync of `root`, or of every product, run to its end by a worker in this
    process."""
    job = job_records.add(JobKind.CATALOG_SYNC, {"root": root}, 3, STARTED_AT)
    run_job(job.id, resolve_paths(os.environ), JobTimings())
    ended = job_records.by_id(job.id)
    assert ended is not None
    return ended


def reports_written() -> dict[str, tuple[pl.DataFrame, pl.DataFrame, str]]:
    """Each report's days, findings, and summary, by its folder under the reports'."""
    reports = resolve_paths(os.environ).reports_dir
    folders = sorted(path.parent for path in reports.rglob(DAYS_FILE_NAME))
    return {
        folder.relative_to(reports).as_posix(): (
            pl.read_parquet(folder / DAYS_FILE_NAME),
            pl.read_parquet(folder / FINDINGS_FILE_NAME),
            (folder / MARKDOWN_FILE_NAME).read_text(encoding="utf-8"),
        )
        for folder in folders
    }


def qualities(client: TestClient) -> dict[str, str]:
    return {each["id"]: each["quality"] for each in client.get("/v1/datasets").json()}


def test_a_sync_run_twice_gives_the_same_reports_and_lists_each_dataset_once(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    # Done means 3.
    store_with("trades", "ohlcv-1s", "ohlcv-1m")
    logged_in(client, container)
    before = client.get("/v1/datasets").json()

    first = synced(job_records, None)
    once = reports_written()
    after_one = client.get("/v1/datasets").json()
    second = synced(job_records, None)
    twice = reports_written()
    after_two = client.get("/v1/datasets").json()

    written = {"reports": [{**CLEAN, "root": "BTCUSDT-PERP"}, {**CLEAN, "root": "ES"}]}
    assert (first.status, first.result) == (JobStatus.SUCCEEDED, written)
    assert (second.status, second.result) == (JobStatus.SUCCEEDED, written)
    assert list(once) == list(twice) == ["synthetic/BTCUSDT-PERP", "synthetic/ES"]
    for folder, (days, findings, summary) in once.items():
        assert_frame_equal(twice[folder][0], days)
        assert_frame_equal(twice[folder][1], findings)
        assert twice[folder][2] == summary
    assert [each["id"] for each in before] == SIX_DATASETS
    assert [each["id"] for each in after_one] == [each["id"] for each in after_two] == SIX_DATASETS
    assert {each["quality"] for each in before} == {"unchecked"}
    assert {each["quality"] for each in after_two} == {"clean"}


def test_a_sync_of_one_product_writes_its_reports_alone(job_records: JobTables) -> None:
    store_with("trades", "ohlcv-1m")

    ended = synced(job_records, "ES")

    assert ended.result == {"reports": [{**CLEAN, "root": "ES"}]}
    assert list(reports_written()) == ["synthetic/ES"]


def test_a_report_older_than_its_data_reads_stale_until_the_next_sync(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    # Quality flows from the reports: unchecked, clean once synced, stale once a partition is
    # newer than its report, as a backfill writes one, and clean again after the next sync.
    store_with("trades", "ohlcv-1m")
    logged_in(client, container)
    unchecked = qualities(client)
    synced(job_records, "ES")
    clean = qualities(client)
    paths = resolve_paths(os.environ)
    oldest = min(path.stat().st_mtime_ns for path in paths.data_dir.rglob("part.parquet"))
    days = paths.reports_dir / "synthetic" / "ES" / DAYS_FILE_NAME
    os.utime(days, ns=(oldest - MINUTE, oldest - MINUTE))

    stale = qualities(client)
    synced(job_records, "ES")
    synced_again = qualities(client)

    es = ("synthetic:ohlcv-1m:ES", "synthetic:trades:ES")
    bitcoin = ("synthetic:ohlcv-1m:BTCUSDT-PERP", "synthetic:trades:BTCUSDT-PERP")
    assert [[seen[each] for each in es] for seen in (unchecked, clean, stale, synced_again)] == [
        ["unchecked", "unchecked"],
        ["clean", "clean"],
        ["stale", "stale"],
        ["clean", "clean"],
    ]
    assert {synced_again[each] for each in bitcoin} == {"unchecked"}


def test_a_sync_of_a_product_the_store_no_longer_holds_fails_with_the_reason(
    job_records: JobTables,
) -> None:
    ended = synced(job_records, "ES")

    assert ended.status == JobStatus.FAILED
    assert ended.error == (
        "NothingToReportError: Expected trades or bars of ES in the store, got none."
    )


def test_a_sync_reports_before_each_report_and_once_all_are_written(
    job_records: JobTables,
) -> None:
    store_with("ohlcv-1m")

    ended = synced(job_records, None)

    events = job_records.events_after(job_stream(ended.id), 0, 100)
    reported = [
        (event.said["percent"], event.said["message"])
        for event in events
        if event.event_type == JobEventType.PROGRESS
    ]
    assert reported == [
        (0.0, "Checking the quality of synthetic BTCUSDT-PERP"),
        (50.0, "Checking the quality of synthetic ES"),
        (100.0, "Checked 2 reports"),
    ]
    assert (ended.status, ended.progress) == (JobStatus.SUCCEEDED, 100.0)
