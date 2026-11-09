"""The streams of step 4.4 (`01-architecture.md` section 6): Server-Sent Events over the events
table, each event's id its row's, a client that reconnects with `Last-Event-ID` given exactly
the events after it, none twice and none missed (Done means 2), new events sent as they are
kept, and a comment while nothing else is sent, every 15 seconds in the server and every 50
milliseconds here, which also bounds every read of these tests."""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi import routing, sse
from fastapi.testclient import TestClient

from fefat_app.container import Container
from fefat_app.database.job_records import JobTables
from fefat_app.ports import Job, JobKind, job_stream
from local_server import STARTED_AT, logged_in

WORKER = 4242
MESSAGES_AT_MOST = 400
"""How many messages a read takes before it gives up: twenty seconds of comments here."""


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
