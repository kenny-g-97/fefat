"""The jobs' records over the app's database (step 4.4, `01-architecture.md` section 6): the
`jobs` table and the `events` of their streams (`fefat_app.ports.JobRecords`). Each call is a
transaction of its own, begun with the write lock, or deferred for a read
(`fefat_app.database.schema`). A change of a job's status is one `UPDATE` whose `WHERE` names the
status it expects, and for a worker's own changes the worker, so that it changes one row or none
however many processes try at once, and the `status` event of the change is written in the same
transaction."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, CursorResult, Engine, Update, select, update
from sqlalchemy.orm import Session

from fefat_app.database.models import EventRow, JobRow
from fefat_app.database.schema import reading
from fefat_app.job_models import (
    Job,
    JobEnd,
    JobEventType,
    JobKind,
    JobStatus,
    StreamEvent,
    job_stream,
)


@dataclass(frozen=True)
class JobTables:
    """`JobRecords` in the tables of `engine`'s database."""

    engine: Engine

    def add(
        self, kind: JobKind, payload: Mapping[str, Any], max_attempts: int, now: datetime
    ) -> Job:
        with Session(self.engine) as session, session.begin():
            return _job(queued_job(session, kind, payload, max_attempts, now))

    def by_id(self, job_id: str) -> Job | None:
        with Session(reading(self.engine)) as session:
            row = session.get(JobRow, job_id)
            return None if row is None else _job(row)

    def recent(self, limit: int) -> tuple[Job, ...]:
        with Session(reading(self.engine)) as session:
            rows = session.scalars(
                select(JobRow).order_by(JobRow.created_at.desc(), JobRow.id.desc()).limit(limit)
            )
            return tuple(_job(row) for row in rows)

    def with_status(self, status: JobStatus) -> tuple[Job, ...]:
        with Session(reading(self.engine)) as session:
            rows = session.scalars(
                select(JobRow).where(JobRow.status == status).order_by(JobRow.created_at, JobRow.id)
            )
            return tuple(_job(row) for row in rows)

    def start(
        self, job_id: str, worker_pid: int, lease_until: datetime, now: datetime
    ) -> Job | None:
        with Session(self.engine) as session, session.begin():
            return _compare_and_set(
                session,
                job_id,
                JobStatus.QUEUED,
                JobStatus.RUNNING,
                None,
                attempt=JobRow.attempt + 1,
                worker_pid=worker_pid,
                lease_expires_at=lease_until,
                started_at=now,
            )

    def renew_lease(self, job_id: str, worker_pid: int, lease_until: datetime) -> bool:
        with Session(self.engine) as session, session.begin():
            return _changed_one(
                session,
                update(JobRow)
                .where(*_held(job_id, worker_pid))
                .values(lease_expires_at=lease_until),
            )

    def advance(
        self,
        job_id: str,
        worker_pid: int,
        percent: float,
        message: str,
        details: Mapping[str, Any],
    ) -> Job | None:
        with Session(self.engine) as session, session.begin():
            advanced = update(JobRow).where(*_held(job_id, worker_pid))
            if not _changed_one(session, advanced.values(progress=percent, message=message)):
                return None
            said = {"percent": percent, "message": message, "details": dict(details)}
            _add_event(session, job_id, JobEventType.PROGRESS, said)
            return _job(session.get_one(JobRow, job_id))

    def finish(
        self,
        job_id: str,
        worker_pid: int,
        end: JobEnd,
        now: datetime,
        *,
        result: Mapping[str, Any] | None = None,
        error: str | None = None,
    ) -> Job | None:
        with Session(self.engine) as session, session.begin():
            return _compare_and_set(
                session,
                job_id,
                JobStatus.RUNNING,
                end,
                worker_pid,
                result_json=None if result is None else dict(result),
                error=error,
                finished_at=now,
            )

    def cancel_queued(self, job_id: str, now: datetime) -> Job | None:
        with Session(self.engine) as session, session.begin():
            return _compare_and_set(
                session, job_id, JobStatus.QUEUED, JobStatus.CANCELLED, None, finished_at=now
            )

    def request_cancel(self, job_id: str, now: datetime) -> Job | None:
        with Session(self.engine) as session, session.begin():
            asked = update(JobRow).where(
                JobRow.id == job_id,
                JobRow.status == JobStatus.RUNNING,
                JobRow.cancel_requested_at.is_(None),
            )
            if not _changed_one(session, asked.values(cancel_requested_at=now)):
                return None
            return _job(session.get_one(JobRow, job_id))

    def requeue(self, job_id: str, worker_pid: int) -> Job | None:
        with Session(self.engine) as session, session.begin():
            return _compare_and_set(
                session,
                job_id,
                JobStatus.RUNNING,
                JobStatus.QUEUED,
                worker_pid,
                JobRow.cancel_requested_at.is_(None),
                worker_pid=None,
                lease_expires_at=None,
                progress=0.0,
                message=None,
            )

    def events_after(self, stream_id: str, after_id: int, limit: int) -> tuple[StreamEvent, ...]:
        with Session(reading(self.engine)) as session:
            rows = session.scalars(
                select(EventRow)
                .where(EventRow.stream_id == stream_id, EventRow.id > after_id)
                .order_by(EventRow.id)
                .limit(limit)
            )
            return tuple(_stream_event(row) for row in rows)


def queued_job(
    session: Session, kind: JobKind, payload: Mapping[str, Any], max_attempts: int, now: datetime
) -> JobRow:
    """A new job of `kind` with `payload`, queued at its first attempt yet to start, with the
    `status` event of its queueing, in the session's transaction, which the runs' records share
    to make a run's row and its job together (step 5.3)."""
    row = JobRow(
        kind=kind,
        payload_json=dict(payload),
        status=JobStatus.QUEUED,
        progress=0.0,
        attempt=0,
        max_attempts=max_attempts,
        created_at=now,
    )
    session.add(row)
    session.flush()
    _add_event(session, row.id, JobEventType.STATUS, {"status": JobStatus.QUEUED.value})
    return row


def _compare_and_set(
    session: Session,
    job_id: str,
    expected: JobStatus,
    to: JobStatus,
    held_by: int | None,
    *also: ColumnElement[bool],
    **changes: Any,
) -> Job | None:
    """Move the job `job_id` from `expected` to `to` with `changes`, where it is held by the
    worker `held_by` if one is named and meets `also`, and write the `status` event of the move;
    None where the job was not so."""
    criteria = [JobRow.id == job_id, JobRow.status == expected, *also]
    if held_by is not None:
        criteria.append(JobRow.worker_pid == held_by)
    if not _changed_one(session, update(JobRow).where(*criteria).values(status=to, **changes)):
        return None
    _add_event(session, job_id, JobEventType.STATUS, {"status": to.value})
    return _job(session.get_one(JobRow, job_id))


def _changed_one(session: Session, statement: Update) -> bool:
    """Whether the `UPDATE` `statement` changed exactly one row, as a compare-and-set must; the
    objects of the session are left as they are, each call reading its job again."""
    changed = session.execute(statement.execution_options(synchronize_session=False))
    if not isinstance(changed, CursorResult):
        raise TypeError(f"Expected the cursor's result of an UPDATE, got {type(changed).__name__}.")
    return changed.rowcount == 1


def _held(job_id: str, worker_pid: int) -> tuple[ColumnElement[bool], ...]:
    """The running job `job_id`, held by the worker `worker_pid`."""
    return (
        JobRow.id == job_id,
        JobRow.status == JobStatus.RUNNING,
        JobRow.worker_pid == worker_pid,
    )


def _add_event(
    session: Session, job_id: str, event_type: JobEventType, said: Mapping[str, Any]
) -> None:
    session.add(
        EventRow(stream_id=job_stream(job_id), event_type=event_type.value, data_json=dict(said))
    )


def _job(row: JobRow) -> Job:
    return Job(
        id=row.id,
        kind=row.kind,
        payload=row.payload_json,
        status=row.status,
        progress=row.progress,
        message=row.message,
        attempt=row.attempt,
        max_attempts=row.max_attempts,
        worker_pid=row.worker_pid,
        lease_expires_at=row.lease_expires_at,
        cancel_requested_at=row.cancel_requested_at,
        result=row.result_json,
        error=row.error,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _stream_event(row: EventRow) -> StreamEvent:
    return StreamEvent(
        id=row.id,
        stream_id=row.stream_id,
        event_type=JobEventType(row.event_type),
        said=row.data_json,
        created_at=row.created_at,
    )
