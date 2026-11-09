"""`GET /v1/streams/{stream_id}` (step 4.4, `01-architecture.md` section 6): Server-Sent Events over
the `events` table, such as a job's progress in `job:<id>`, read by the web app's jobs drawer and
home page. Each event's id is its row's, which counts up and is never used again, so that a
client that lost the connection asks again with `Last-Event-ID` and gets the events after it,
none twice and none missed; without it, the stream starts at its first event. The workers write
the events from their own processes, so the stream reads the table every half second; FastAPI
sends a comment every 15 seconds while nothing else is sent, so that the connection stays open
through a quiet stretch, and the stream ends only when the client goes."""

import asyncio
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.concurrency import run_in_threadpool
from fastapi.sse import EventSourceResponse, ServerSentEvent

from fefat_app.http.api_prefix import API_PREFIX
from fefat_app.http.dependencies import ContainerDependency, the_identity
from fefat_app.http.problems import problem_responses

router = APIRouter(prefix=API_PREFIX, tags=["streams"], dependencies=[Depends(the_identity)])

EVENTS_PER_READ = 500
"""How many events one read of the table takes at most."""
READ_EVERY_SECONDS = 0.5
"""How long the stream waits for new events after a read that found fewer than it could take."""


@router.get(
    "/streams/{stream_id}",
    response_class=EventSourceResponse,
    responses=problem_responses(401, 422),
)
async def stream_events(
    stream_id: str,
    container: ContainerDependency,
    last_event_id: Annotated[int | None, Header()] = None,
) -> AsyncIterator[ServerSentEvent]:
    """The events of the stream `stream_id`, such as `job:<id>`, after the event `Last-Event-ID`
    names, or from the first, then each new one as it is kept; each event's `id` is what to send
    as `Last-Event-ID` on reconnecting, its `event` its type, and its `data` what it says."""
    after = 0 if last_event_id is None else last_event_id
    while True:
        events = await run_in_threadpool(
            container.jobs.events_after, stream_id, after, EVENTS_PER_READ
        )
        for event in events:
            yield ServerSentEvent(id=str(event.id), event=event.event_type, data=event.data)
            after = event.id
        if len(events) < EVENTS_PER_READ:
            await asyncio.sleep(READ_EVERY_SECONDS)
