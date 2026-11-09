"""The jobs' routes of step 4.4 (`01-architecture.md` sections 6 and 7): the list newest first, a
job by its id, a cancel that ends a queued job at once and asks a running one to stop, the demo
job started and run in the pool to its end (Done means 1), each behind the login, the cancel and
the start with the session's CSRF token, and an API token allowed as for every route that a
notebook may call."""

import time
from datetime import timedelta

from fastapi.testclient import TestClient

from fefat_app.container import Container
from fefat_app.database.job_records import JobTables
from fefat_app.ports import Job, JobKind
from local_server import STARTED_AT, SettableClock, logged_in

PROBLEM = "application/problem+json"
DEADLINE_SECONDS = 60


def a_demo(job_records: JobTables, clock: SettableClock) -> Job:
    """A demo job in the records, which no worker is given (the tests' reaper waits an hour)."""
    job = job_records.add(JobKind.DEMO, {"seconds": 60}, 3, clock())
    clock.advance(timedelta(seconds=1))
    return job


def test_the_jobs_come_newest_first(
    client: TestClient, container: Container, job_records: JobTables, clock: SettableClock
) -> None:
    logged_in(client, container)
    empty = client.get("/v1/jobs")
    older, newer = a_demo(job_records, clock), a_demo(job_records, clock)

    listed = client.get("/v1/jobs")

    assert (empty.status_code, empty.json()) == (200, [])
    assert [job["id"] for job in listed.json()] == [newer.id, older.id]
    assert listed.json()[1] == {
        "id": older.id,
        "kind": "demo",
        "payload": {"seconds": 60},
        "status": "queued",
        "progress": 0.0,
        "message": None,
        "attempt": 0,
        "max_attempts": 3,
        "worker_pid": None,
        "lease_expires_at": None,
        "cancel_requested_at": None,
        "result": None,
        "error": None,
        "created_at": "2026-11-06T09:00:00Z",
        "started_at": None,
        "finished_at": None,
    }


def test_a_job_is_read_by_its_id_and_an_unknown_one_is_a_problem(
    client: TestClient, container: Container, job_records: JobTables, clock: SettableClock
) -> None:
    logged_in(client, container)
    job = a_demo(job_records, clock)

    found = client.get(f"/v1/jobs/{job.id}")
    unknown = client.get("/v1/jobs/nope")

    assert (found.status_code, found.json()["id"]) == (200, job.id)
    assert (unknown.status_code, unknown.headers["content-type"]) == (404, PROBLEM)
    assert unknown.json()["detail"] == "Expected the id of a job, got 'nope'."


def test_a_queued_job_is_cancelled_at_once(
    client: TestClient, container: Container, job_records: JobTables, clock: SettableClock
) -> None:
    # Done means 1: cancellation.
    csrf = logged_in(client, container)
    job = a_demo(job_records, clock)

    cancelled = client.post(f"/v1/jobs/{job.id}/cancel", headers=csrf)

    assert cancelled.status_code == 200
    assert (cancelled.json()["status"], cancelled.json()["finished_at"]) == (
        "cancelled",
        "2026-11-06T09:00:01Z",
    )


def test_a_running_job_is_asked_to_stop(
    client: TestClient, container: Container, job_records: JobTables, clock: SettableClock
) -> None:
    # Done means 1: the worker reads the request at its next report (test_local_dispatcher).
    csrf = logged_in(client, container)
    job = a_demo(job_records, clock)
    job_records.start(job.id, 4242, clock() + timedelta(seconds=15), clock())

    asked = client.post(f"/v1/jobs/{job.id}/cancel", headers=csrf)

    assert asked.status_code == 200
    assert (asked.json()["status"], asked.json()["cancel_requested_at"]) == (
        "running",
        "2026-11-06T09:00:01Z",
    )


def test_a_cancel_of_an_unknown_job_is_a_problem(client: TestClient, container: Container) -> None:
    csrf = logged_in(client, container)

    refused = client.post("/v1/jobs/nope/cancel", headers=csrf)

    assert (refused.status_code, refused.headers["content-type"]) == (404, PROBLEM)


def test_the_jobs_need_a_login_and_their_changes_the_csrf_token(
    client: TestClient, container: Container, job_records: JobTables, clock: SettableClock
) -> None:
    job = a_demo(job_records, clock)
    anonymous = client.get("/v1/jobs")
    logged_in(client, container)

    unsigned_cancel = client.post(f"/v1/jobs/{job.id}/cancel")
    unsigned_start = client.post("/v1/jobs/demo", json={"seconds": 1})

    assert anonymous.status_code == 401
    assert (unsigned_cancel.status_code, unsigned_start.status_code) == (403, 403)
    assert job_records.recent(10) == (job,)


def test_an_api_token_lists_and_cancels_jobs(
    client: TestClient, container: Container, job_records: JobTables, clock: SettableClock
) -> None:
    job = a_demo(job_records, clock)
    bearer = {"Authorization": f"Bearer {container.api_tokens.create('notebook')}"}

    listed = client.get("/v1/jobs", headers=bearer)
    cancelled = client.post(f"/v1/jobs/{job.id}/cancel", headers=bearer)

    assert [found["id"] for found in listed.json()] == [job.id]
    assert cancelled.json()["status"] == "cancelled"


def test_a_demo_of_no_seconds_or_more_than_an_hour_is_refused(
    client: TestClient, container: Container
) -> None:
    csrf = logged_in(client, container)

    refusals = [
        client.post("/v1/jobs/demo", json={"seconds": seconds}, headers=csrf)
        for seconds in (0, 3601)
    ]

    assert [refused.status_code for refused in refusals] == [422, 422]


def test_a_demo_job_started_through_the_api_runs_in_the_pool_to_its_end(
    client: TestClient, container: Container
) -> None:
    # Done means 1: the one test of the routes that runs a worker of the pool.
    csrf = logged_in(client, container)

    started = client.post("/v1/jobs/demo", json={"seconds": 1}, headers=csrf)
    job_id = started.json()["id"]
    deadline = time.monotonic() + DEADLINE_SECONDS
    ended = client.get(f"/v1/jobs/{job_id}").json()
    while ended["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(0.1)
        ended = client.get(f"/v1/jobs/{job_id}").json()

    assert (started.status_code, started.json()["status"]) == (202, "queued")
    assert started.json()["created_at"] == STARTED_AT.isoformat().replace("+00:00", "Z")
    assert (ended["status"], ended["result"], ended["progress"]) == (
        "succeeded",
        {"counted": 1},
        100.0,
    )
