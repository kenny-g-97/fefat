"""The streams of step 4.4 (`01-architecture.md` section 6): Server-Sent Events over the events
table, each event's id its row's, a client that reconnects with `Last-Event-ID` given exactly
the events after it, none twice and none missed (Done means 2), new events sent as they are
kept, and a comment while nothing else is sent, every 15 seconds in the server and every 50
milliseconds here, which also bounds every read of these tests. From step 5.19: one stream of
every job's events, which replays nothing when opened anew, and a login checked at each read,
so that a stream ends with its session or its token, and a job's own at its last status."""

import json
from collections.abc import Iterator
from datetime import timedelta
from itertools import islice

import pytest
from fastapi import routing, sse
from fastapi.testclient import TestClient

from fefat_app.container import Container
from fefat_app.database.job_records import JobTables
from fefat_app.job_models import Job, JobKind, JobStatus, job_stream
from local_server import STARTED_AT, logged_in

WORKER = 4242
MESSAGES_AT_MOST = 400
"""How many messages a read takes before it gives up: twenty seconds of comments here."""
EVERY_JOB = "/v1/streams/jobs"


@pytest.fixture(autouse=True)
def quick_comments(monkeypatch: pytest.MonkeyPatch) -> None:
    """The comment that keeps a quiet stream open every 50 milliseconds rather than 15 seconds."""
    assert sse._PING_INTERVAL == 15.0
    monkeypatch.setattr(routing, "_PING_INTERVAL", 0.05)


def a_running_demo(job_records: JobTables, reports: int) -> Job:
    """A demo job that started and reported `reports` times: two status events, then reports."""
    job = job_records.add(JobKind.DEMO, {"seconds": 10}, 3, STARTED_AT)
    job_records.start(job.id, WORKER, STARTED_AT + timedelta(seconds=15), STARTED_AT)
    for count in range(1, reports + 1):
        job_records.advance(job.id, WORKER, count * 10.0, f"Counted {count} of 10", {})
    return job


def next_message(lines: Iterator[str]) -> dict[str, str]:
    """The next message of an event stream: an event's fields, or a comment's text."""
    fields: dict[str, str] = {}
    for line in lines:
        if line == "":
            if fields:
                return fields
            continue
        if line.startswith(":"):
            fields["comment"] = line.removeprefix(":").strip()
            continue
        name, _, value = line.partition(":")
        fields[name] = value.removeprefix(" ")
    raise AssertionError("Expected another message, got the end of the stream.")


def next_events(lines: Iterator[str], count: int) -> list[dict[str, str]]:
    """The next `count` events of an event stream, past its comments."""
    events: list[dict[str, str]] = []
    for _ in range(MESSAGES_AT_MOST):
        message = next_message(lines)
        if "comment" not in message:
            events.append(message)
        if len(events) == count:
            return events
    raise AssertionError(f"Expected {count} events, got {len(events)} in {MESSAGES_AT_MOST}.")


def ends(lines: Iterator[str]) -> bool:
    """Whether the stream ends within `MESSAGES_AT_MOST` more lines, ten seconds of comments."""
    return next(islice(lines, MESSAGES_AT_MOST, None), None) is None


def stream_of(route: str, job: Job) -> str:
    """The address of the stream of every job, or of `job`'s own."""
    return EVERY_JOB if route == "every job" else f"/v1/streams/{job_stream(job.id)}"


def test_a_stream_of_every_job_opened_anew_replays_no_event(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    # Done means 1: the job reported 80 % before the reaper queued it again, and a reload must
    # show no figure of that attempt, so the stream opened now starts after all of it.
    logged_in(client, container)
    job = a_running_demo(job_records, reports=8)
    job_records.requeue(job.id, WORKER)
    job_records.start(job.id, WORKER, STARTED_AT + timedelta(seconds=15), STARTED_AT)

    with client.stream("GET", EVERY_JOB) as opened:
        lines = opened.iter_lines()
        quiet = next_message(lines)
        job_records.advance(job.id, WORKER, 10.0, "Counted 1 of 10", {})
        first = next_events(lines, 1)[0]

    assert quiet == {"comment": "ping"}
    assert first["event"] == "progress"
    assert json.loads(first["data"]) == {
        "percent": 10.0,
        "message": "Counted 1 of 10",
        "details": {},
        "job_id": job.id,
    }


def test_one_stream_carries_the_events_of_five_running_jobs(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    # Done means 1: a fifth active job moves too.
    logged_in(client, container)
    jobs = [a_running_demo(job_records, reports=0) for _ in range(5)]

    with client.stream("GET", EVERY_JOB) as opened:
        for position, job in enumerate(jobs, start=1):
            job_records.advance(job.id, WORKER, position * 10.0, f"Counted {position}", {})
        events = next_events(opened.iter_lines(), 5)

    reports = [json.loads(event["data"]) for event in events]
    assert [(report["job_id"], report["percent"]) for report in reports] == [
        (job.id, position * 10.0) for position, job in enumerate(jobs, start=1)
    ]


def test_a_stream_of_every_job_resumes_with_every_event_once(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    logged_in(client, container)
    job = a_running_demo(job_records, reports=0)

    with client.stream("GET", EVERY_JOB) as first:
        job_records.advance(job.id, WORKER, 10.0, "Counted 1 of 10", {})
        job_records.advance(job.id, WORKER, 20.0, "Counted 2 of 10", {})
        before = next_events(first.iter_lines(), 1)
    job_records.advance(job.id, WORKER, 30.0, "Counted 3 of 10", {})
    with client.stream("GET", EVERY_JOB, headers={"Last-Event-ID": before[0]["id"]}) as second:
        after = next_events(second.iter_lines(), 2)

    percents = [json.loads(event["data"])["percent"] for event in [*before, *after]]
    assert percents == [10.0, 20.0, 30.0]


def test_a_resume_past_the_newest_event_starts_at_the_newest(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    # An id of a database since replaced would otherwise hide every event until the ids pass it.
    logged_in(client, container)
    job = a_running_demo(job_records, reports=0)

    with client.stream("GET", EVERY_JOB, headers={"Last-Event-ID": "999999"}) as opened:
        job_records.advance(job.id, WORKER, 10.0, "Counted 1 of 10", {})
        event = next_events(opened.iter_lines(), 1)[0]

    assert json.loads(event["data"])["percent"] == 10.0


@pytest.mark.parametrize("route", ["every job", "its job"])
def test_a_stream_ends_within_a_read_of_its_sessions_logout(
    client: TestClient, container: Container, job_records: JobTables, route: str
) -> None:
    # Done means 2.
    csrf = logged_in(client, container)
    job = a_running_demo(job_records, reports=0)

    with client.stream("GET", stream_of(route, job)) as opened:
        lines = opened.iter_lines()
        next_message(lines)
        logout = client.post("/v1/auth/logout", headers=csrf)
        ended = ends(lines)

    assert logout.status_code == 204
    assert ended


@pytest.mark.parametrize("route", ["every job", "its job"])
def test_a_stream_ends_within_a_read_of_its_tokens_revocation(
    client: TestClient, container: Container, job_records: JobTables, route: str
) -> None:
    # Done means 2.
    token = container.api_tokens.create("notebook")
    job = a_running_demo(job_records, reports=0)
    bearer = {"Authorization": f"Bearer {token}"}

    with client.stream("GET", stream_of(route, job), headers=bearer) as opened:
        lines = opened.iter_lines()
        next_message(lines)
        container.api_tokens.revoke("notebook")
        ended = ends(lines)

    assert ended


def test_a_jobs_stream_ends_after_its_last_status(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    logged_in(client, container)
    job = a_running_demo(job_records, reports=1)
    stream = f"/v1/streams/{job_stream(job.id)}"

    with client.stream("GET", stream) as opened:
        lines = opened.iter_lines()
        before = next_events(lines, 3)
        job_records.finish(job.id, WORKER, JobStatus.CANCELLED, STARTED_AT)
        last = next_events(lines, 1)[0]
        ended = ends(lines)

    assert [event["event"] for event in before] == ["status", "status", "progress"]
    assert last["data"] == '{"status": "cancelled"}'
    assert ended


def test_a_reconnect_after_a_jobs_last_event_is_told_to_stop(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    # An event source reconnects whenever a response ends, unless it is answered 204.
    logged_in(client, container)
    job = a_running_demo(job_records, reports=0)
    job_records.finish(job.id, WORKER, JobStatus.FAILED, STARTED_AT, error="It failed.")
    stream = f"/v1/streams/{job_stream(job.id)}"
    last = job_records.events_after(job_stream(job.id), 0, 100)[-1]

    told = client.get(stream, headers={"Last-Event-ID": str(last.id)})
    earlier = client.get(stream, headers={"Last-Event-ID": str(last.id - 1)})

    assert (told.status_code, told.content) == (204, b"")
    assert earlier.status_code == 200
    assert '"failed"' in earlier.text


def test_the_stream_of_a_job_that_does_not_exist_is_a_problem(
    client: TestClient, container: Container
) -> None:
    logged_in(client, container)

    answer = client.get(f"/v1/streams/{job_stream('no-such-job')}")

    assert (answer.status_code, answer.headers["content-type"]) == (
        404,
        "application/problem+json",
    )


def test_the_stream_of_every_job_needs_a_login(client: TestClient) -> None:
    assert client.get(EVERY_JOB).status_code == 401


def test_a_client_that_reconnects_gets_every_event_once(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    # Done means 2: no duplicate or missing event across a disconnect.
    logged_in(client, container)
    job = a_running_demo(job_records, reports=3)
    stream = f"/v1/streams/{job_stream(job.id)}"

    with client.stream("GET", stream) as first:
        content_type = first.headers["content-type"]
        before = next_events(first.iter_lines(), 3)
    with client.stream("GET", stream, headers={"Last-Event-ID": before[-1]["id"]}) as second:
        lines = second.iter_lines()
        after = next_events(lines, 2)
        quiet = next_message(lines)
        job_records.advance(job.id, WORKER, 40.0, "Counted 4 of 10", {"count": 4})
        live = next_events(lines, 1)

    kept = job_records.events_after(job_stream(job.id), 0, 100)
    received = before + after + live
    assert content_type.startswith("text/event-stream")
    assert [int(event["id"]) for event in received] == [event.id for event in kept]
    assert [event["event"] for event in received] == [
        "status",
        "status",
        "progress",
        "progress",
        "progress",
        "progress",
    ]
    assert quiet == {"comment": "ping"}
    assert live[0]["data"] == (
        '{"percent": 40.0, "message": "Counted 4 of 10", "details": {"count": 4}}'
    )


def test_a_stream_without_a_last_event_id_starts_at_its_first_event(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    logged_in(client, container)
    job = a_running_demo(job_records, reports=0)

    with client.stream("GET", f"/v1/streams/{job_stream(job.id)}") as opened:
        events = next_events(opened.iter_lines(), 2)

    assert [(event["event"], event["data"]) for event in events] == [
        ("status", '{"status": "queued"}'),
        ("status", '{"status": "running"}'),
    ]


def test_a_stream_needs_a_login_and_a_numeric_last_event_id(
    client: TestClient, container: Container, job_records: JobTables
) -> None:
    job = a_running_demo(job_records, reports=0)
    stream = f"/v1/streams/{job_stream(job.id)}"

    anonymous = client.get(stream)
    logged_in(client, container)
    garbled = client.get(stream, headers={"Last-Event-ID": "abc"})

    assert anonymous.status_code == 401
    assert (garbled.status_code, garbled.headers["content-type"]) == (
        422,
        "application/problem+json",
    )
