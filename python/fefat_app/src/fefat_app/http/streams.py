"""`GET /v1/streams/jobs` and `GET /v1/streams/{stream_id}` (steps 4.4 and 5.19,
`01-architecture.md` section 6): Server-Sent Events over the `events` table. The first carries
every job's events, one stream per tab of the web app, each naming its `job_id`; the second one
stream's, such as a job's in `job:<id>`, for a script. Each event's id is its row's, which counts
up and is never used again, so that a client that lost the connection asks again with
`Last-Event-ID` and gets the events after it, none twice and none missed. Without it, the stream
of every job starts after the newest event, fixed before the response begins, so that a reload
replays no earlier attempt's figures and a list read once the stream is open misses nothing,
while one stream starts at its first event. The workers write the events from their own
processes, so a stream reads the table every half second, and checks its login before each read,
ending once its session or token has; a job's own stream also ends after the job's last status.
FastAPI sends a comment every 15 seconds while nothing else is sent, so that the connection stays
open through a quiet stretch."""

import asyncio
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.sse import EventSourceResponse, ServerSentEvent

from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, LoginCheckDependency, the_identity
from fefat_app.http.problems import problem_responses
from fefat_app.job_models import StreamEvent, job_of_stream
from fefat_app.services.jobs import NoSuchJobError

router = APIRouter(prefix=API_PREFIX, tags=["streams"], dependencies=[Depends(the_identity)])

EVENTS_PER_READ = 500
"""How many events one read of the table takes at most."""
READ_EVERY_SECONDS = 0.5
"""How long a stream waits for new events after a read that found fewer than it could take."""
NOTHING_MORE = {204: {"description": "The job has ended and no event follows `Last-Event-ID`."}}

LastEventId = Annotated[int | None, Header()]


def _start_of_every_job(container: ContainerDependency, last_event_id: LastEventId = None) -> int:
    """The event the stream of every job starts after: the one named, unless the table holds no
    such event, as after the database was replaced, or else the newest."""
    newest = container.jobs.newest_event_id()
    return newest if last_event_id is None else min(last_event_id, newest)


def _start_of_one_stream(
    stream_id: str, container: ContainerDependency, last_event_id: LastEventId = None
) -> int:
    """The event the stream `stream_id` starts after; refused before the response begins with
    404 for a job that does not exist, and with 204, which tells an event source to stop
    reconnecting, for a job that has ended with no event left to send."""
    after = 0 if last_event_id is None else last_event_id
    job_id = job_of_stream(stream_id)
    if job_id is None:
        return after
    try:
        ended = container.jobs.has_ended(job_id)
    except NoSuchJobError as unknown:
        raise HTTPException(404, str(unknown)) from unknown
    if ended and not container.jobs.events_after(stream_id, after, 1):
        raise HTTPException(204)
    return after


@router.get(
    "/streams/jobs",
    response_class=EventSourceResponse,
    responses=problem_responses(401, 422),
)
async def stream_every_job(
    container: ContainerDependency,
    still_logged_in: LoginCheckDependency,
    start: Annotated[int, Depends(_start_of_every_job)],
) -> AsyncIterator[ServerSentEvent]:
    """Every job's events after `Last-Event-ID`, or those kept from now on, each saying what its
    job's stream says with its `job_id`, until the session or the token ends."""
    events = _followed(
        lambda after: container.jobs.job_events_after(after, EVENTS_PER_READ),
        start,
        still_logged_in,
        lambda: False,
        _said_with_its_job,
    )
    async for event in events:
        yield event


@router.get(
    "/streams/{stream_id}",
    response_class=EventSourceResponse,
    responses={**problem_responses(401, 404, 422), **NOTHING_MORE},
)
async def stream_events(
    stream_id: str,
    container: ContainerDependency,
    still_logged_in: LoginCheckDependency,
    start: Annotated[int, Depends(_start_of_one_stream)],
) -> AsyncIterator[ServerSentEvent]:
    """The events of the stream `stream_id`, such as `job:<id>`, after the event `Last-Event-ID`
    names, or from the first, then each new one as it is kept, until the session or the token
    ends or, for a job, after its last status; each event's `id` is what to send as
    `Last-Event-ID` on reconnecting, its `event` its type, and its `data` what it says."""
    job_id = job_of_stream(stream_id)
    events = _followed(
        lambda after: container.jobs.events_after(stream_id, after, EVENTS_PER_READ),
        start,
        still_logged_in,
        (lambda: False) if job_id is None else (lambda: container.jobs.has_ended(job_id)),
        lambda event: event.said,
    )
    async for event in events:
        yield event


async def _followed(
    read_after: Callable[[int], tuple[StreamEvent, ...]],
    start: int,
    still_logged_in: Callable[[], bool],
    has_ended: Callable[[], bool],
    said: Callable[[StreamEvent], Mapping[str, Any]],
) -> AsyncIterator[ServerSentEvent]:
    """The events `read_after` gives after `start`, read while the login holds, until a read made
    after `has_ended` said true has sent all there was: an end's status event is kept with it."""
    after = start
    while await run_in_threadpool(still_logged_in):
        ended = await run_in_threadpool(has_ended)
        events = await run_in_threadpool(read_after, after)
        for event in events:
            yield ServerSentEvent(id=str(event.id), event=event.event_type, data=said(event))
            after = event.id
        if len(events) == EVENTS_PER_READ:
            continue
        if ended:
            return
        await asyncio.sleep(READ_EVERY_SECONDS)


def _said_with_its_job(event: StreamEvent) -> Mapping[str, Any]:
    return {**event.said, "job_id": job_of_stream(event.stream_id)}
