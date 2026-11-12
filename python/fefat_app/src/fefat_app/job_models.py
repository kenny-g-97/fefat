"""The jobs' models (`01-architecture.md` section 6, step 4.4, D-90): what a job runs, where it
stands, how it ends, and the events of its stream, which the jobs' records (`fefat_app.ports.
JobRecords`), the dispatcher, the workers, and the services share. They moved out of the ports'
module at step 5.3, as `fefat_app.execution` and `fefat_app.library` hold the executor's and the
library's, so that the runs' models read them without the ports (`BACKLOG.md`)."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict


class JobKind(StrEnum):
    """What a job runs (`01-architecture.md` section 6); a later phase adds its kinds."""

    BACKTEST = "backtest"
    FEATURE_PREVIEW = "feature_preview"
    FEATURE_VALIDATE = "feature_validate"
    ANALYTICS = "analytics"
    STUDY = "study"
    PROP_SIM = "prop_sim"
    SOURCE_SYNC = "source_sync"
    IMPORT = "import"
    TRADE_IMPORT = "trade_import"
    CATALOG_SYNC = "catalog_sync"
    REPRODUCE = "reproduce"
    AGENT_TURN = "agent_turn"
    INGEST = "ingest"
    DEMO = "demo"
    PYTHON_SNIPPET = "python_snippet"


class JobStatus(StrEnum):
    """Where a job stands (`01-architecture.md` section 6): queued, then running, then one of
    four ends, each change a compare-and-set update; a running job whose worker stopped
    answering is queued again while it has attempts left (step 4.4, D-90)."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


ACTIVE = (JobStatus.QUEUED, JobStatus.RUNNING)
"""The statuses of a job that has not ended, queued before running."""

type JobEnd = Literal[
    JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.TIMED_OUT
]
"""The statuses a running job ends in."""


class JobEventType(StrEnum):
    """What an event of a job's stream says: how far the job has come, with its message and any
    figures its kind reports, or the status it moved to."""

    PROGRESS = "progress"
    STATUS = "status"


def job_stream(job_id: str) -> str:
    """The stream of the job `job_id`'s events (`01-architecture.md` section 6)."""
    return f"job:{job_id}"


class Job(BaseModel):
    """A job as the app keeps it (`01-architecture.md` section 6): what it runs and with what,
    where it stands, how far it has come, in percent, with its last message, its attempts, the
    worker process that holds it and until when its lease runs, when it was asked to stop, and
    how it ended."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: JobKind
    payload: dict[str, Any]
    status: JobStatus
    progress: float
    message: str | None
    attempt: int
    max_attempts: int
    worker_pid: int | None
    lease_expires_at: AwareDatetime | None
    cancel_requested_at: AwareDatetime | None
    result: dict[str, Any] | None
    error: str | None
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None


class StreamEvent(BaseModel):
    """An event of a stream, such as `job:<id>` (`01-architecture.md` section 6): its id, which
    counts up and which a reader resumes after, its type, what it says, and when it was kept. The
    jobs' types are the only ones so far; the agent's turns add theirs (Phase 8)."""

    model_config = ConfigDict(frozen=True)

    id: int
    stream_id: str
    event_type: JobEventType
    said: dict[str, Any]
    created_at: AwareDatetime
