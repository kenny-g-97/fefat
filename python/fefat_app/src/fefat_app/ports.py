"""The app's seams (`01-architecture.md` section 10, `08-code-design.md` section 1, D-27): each a
`typing.Protocol` that an adapter implements, built once in `fefat_app.container` and passed to
what uses it, so that swapping an adapter is a module of its own and a line of the container.

The credential store is the first (step 4.1), the records of who may use the local server the
second (step 4.2), the trader's preferences the third (step 4.3), the jobs' records and their
dispatcher the fourth and fifth (step 4.4), their models in `fefat_app.job_models` (step 5.3),
the executor the sixth (step 4.5), its specs and
results in `fefat_app.execution`, and the library's index the seventh (step 5.2), its rows in
`fefat_app.library`; the blob store, the agent's runtime, and the licence arrive with the steps
that first use them."""

from collections.abc import Callable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict

from fefat_app.execution import (
    ExecutionResult,
    ExecutionSpec,
    ProgressReport,
    StopCheck,
    keep_running,
)
from fefat_app.job_models import Job, JobEnd, JobKind, JobStatus, StreamEvent
from fefat_app.library import IndexedFeature, IndexedStrategy

type Clock = Callable[[], datetime]
"""Now, as an aware instant in UTC: the system's clock in the server, a settable one in tests."""


class SecretName(StrEnum):
    """The secrets FEAT keeps, each the key of a service it calls: the agent's model provider
    (Phase 8) and a market data vendor (D-37). The list is closed, since a credential store
    cannot list what it holds; a step that calls another service adds its name."""

    ANTHROPIC = "anthropic"
    DATABENTO = "databento"


class CredentialStore(Protocol):
    """Where the secrets live: the operating system's credential store, never `config.toml` or
    another file FEFAT writes (`01-architecture.md` section 8)."""

    def get(self, name: SecretName) -> str | None:
        """The secret `name`, or None where none is stored."""
        ...

    def set(self, name: SecretName, value: str) -> None:
        """Store `value` as the secret `name`, in place of any stored before; an empty value is
        refused."""
        ...

    def delete(self, name: SecretName) -> None:
        """Remove the secret `name`, refused where none is stored."""
        ...


class LoginSession(BaseModel):
    """A login session of the local server: when it ends and when it was last seen. The token
    its cookie carries is kept only as its SHA-256, which names it."""

    model_config = ConfigDict(frozen=True)

    expires_at: AwareDatetime
    last_seen_at: AwareDatetime


class ApiToken(BaseModel):
    """An API token of a notebook or a script, by its name, kept only as its SHA-256, which
    names it, with when it was made and last used."""

    model_config = ConfigDict(frozen=True)

    name: str
    created_at: AwareDatetime
    last_used_at: AwareDatetime | None


class TokenNameInUseError(ValueError):
    """A new API token under a name a token has, or had before its revocation."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Expected a new token name, got {name!r}, which a token has.")


class AccessRecords(Protocol):
    """What lets a client into the local server (step 4.2, D-86): the password's Argon2 hash,
    the login sessions, and the API tokens, each token known by its SHA-256 alone, so that the
    records hold nothing a client could present."""

    def password_hash(self) -> str | None:
        """The password's Argon2 hash, or None before a password is set."""
        ...

    def replace_password_hash(self, password_hash: str, changed_at: datetime) -> None:
        """Keep `password_hash` as the password's, in place of any before, and end every login
        session in the same transaction; one that replaces another revokes every live API
        token at `changed_at` too (step 5.2)."""
        ...

    def add_session(self, token_hash: str, created_at: datetime, expires_at: datetime) -> None:
        """Begin a login session for the token of SHA-256 `token_hash`, last seen when made."""
        ...

    def session_by_hash(self, token_hash: str) -> LoginSession | None:
        """The login session of the token of SHA-256 `token_hash`, or None."""
        ...

    def mark_session_seen(self, token_hash: str, seen_at: datetime) -> None:
        """Record that the login session of the token of SHA-256 `token_hash` was seen, or give
        it up while another writer holds the records, the next request recording it."""
        ...

    def remove_session(self, token_hash: str) -> None:
        """End the login session of the token of SHA-256 `token_hash`, if there is one."""
        ...

    def remove_expired_sessions(self, now: datetime) -> None:
        """End every login session whose end is not after `now`."""
        ...

    def add_api_token(self, name: str, token_hash: str, created_at: datetime) -> None:
        """Keep the API token of SHA-256 `token_hash` under `name`; a name in use is refused
        with `TokenNameInUseError`."""
        ...

    def api_token_by_hash(self, token_hash: str) -> ApiToken | None:
        """The API token of SHA-256 `token_hash`, or None, which a revoked token gives too."""
        ...

    def live_api_tokens(self) -> tuple[ApiToken, ...]:
        """The API tokens not revoked, by when they were made, then by name."""
        ...

    def revoke_api_token(self, name: str, revoked_at: datetime) -> bool:
        """Revoke the live API token `name`, which is refused from then on; whether there was
        one."""
        ...

    def mark_api_token_used(self, token_hash: str, used_at: datetime) -> None:
        """Record that the API token of SHA-256 `token_hash` was used, or give it up while
        another writer holds the records, the next request recording it."""
        ...


class Theme(StrEnum):
    """The web app's colours (`web/DESIGN.md`): dark, the default the design brief sets, or
    light."""

    DARK = "dark"
    LIGHT = "light"


class Preferences(Protocol):
    """What the trader chooses in the app, which the app keeps for them in its database's
    `settings` table (D-83), never in `config.toml`: the theme so far."""

    def theme(self) -> Theme:
        """The theme chosen, dark before any choice."""
        ...

    def replace_theme(self, theme: Theme) -> None:
        """Keep `theme` as the theme, in place of any chosen before."""
        ...


class JobRecords(Protocol):
    """The jobs and their streams' events (step 4.4): each call a transaction of its own, each
    change of a job's status a compare-and-set update that gives None where the job was not in
    the status it expects, and writes a `status` event to the job's stream with the change. A
    worker's own changes also expect the job to be held by the worker's process, so that a
    worker the reaper gave up on changes nothing."""

    def add(
        self, kind: JobKind, payload: Mapping[str, Any], max_attempts: int, now: datetime
    ) -> Job:
        """Queue a new job of `kind` with `payload`, at its first attempt yet to start."""
        ...

    def by_id(self, job_id: str) -> Job | None:
        """The job `job_id`, or None."""
        ...

    def recent(self, limit: int) -> tuple[Job, ...]:
        """The `limit` newest jobs, newest first."""
        ...

    def with_status(self, status: JobStatus) -> tuple[Job, ...]:
        """The jobs in `status`, oldest first."""
        ...

    def start(
        self, job_id: str, worker_pid: int, lease_until: datetime, now: datetime
    ) -> Job | None:
        """Move the queued job `job_id` to running in the worker `worker_pid`, at its next
        attempt, leased until `lease_until`."""
        ...

    def renew_lease(self, job_id: str, worker_pid: int, lease_until: datetime) -> bool:
        """Extend the lease of the running job `job_id` that `worker_pid` holds; whether it
        holds it."""
        ...

    def advance(
        self,
        job_id: str,
        worker_pid: int,
        percent: float,
        message: str,
        details: Mapping[str, Any],
    ) -> Job | None:
        """Record how far the running job `job_id` that `worker_pid` holds has come, with a
        `progress` event; the job, whose `cancel_requested_at` says whether to stop."""
        ...

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
        """End the running job `job_id` that `worker_pid` holds in `end`."""
        ...

    def cancel_queued(self, job_id: str, now: datetime) -> Job | None:
        """End the queued job `job_id` as cancelled before any worker starts it."""
        ...

    def request_cancel(self, job_id: str, now: datetime) -> Job | None:
        """Ask the running job `job_id` to stop, unless it was asked before; it stays running
        until its worker stops it, or the reaper does after the grace (step 4.4)."""
        ...

    def requeue(self, job_id: str, worker_pid: int) -> Job | None:
        """Queue the running job `job_id`, whose worker `worker_pid` stopped answering, again,
        from the start, keeping the attempts it spent; None where it was asked to stop, which
        the reaper then ends as cancelled."""
        ...

    def events_after(self, stream_id: str, after_id: int, limit: int) -> tuple[StreamEvent, ...]:
        """At most `limit` events of the stream `stream_id` after the event `after_id`, in the
        order they were kept."""
        ...


class Dispatcher(Protocol):
    """Where the queued jobs run (`01-architecture.md` section 10): the local process pool, or
    remote workers one day. Its reaper queues again, or ends, a running job whose worker stopped
    answering, and ends a job asked to stop that runs on past the grace (step 4.4); a job is
    cancelled through its records, which its worker reads between chunks."""

    def start(self) -> None:
        """Begin reaping, as the server starts."""
        ...

    def submit(self, job_id: str) -> None:
        """Run the queued job `job_id` once a worker is free."""
        ...

    def close(self) -> None:
        """Stop reaping and end every worker, as the server stops; their jobs are queued again
        when it starts next."""
        ...


class Executor(Protocol):
    """Where the trader's code runs (`01-architecture.md` sections 6 and 10, step 4.5): a
    subprocess within a wall-clock timeout and a memory limit, in a scrubbed environment, today,
    and containers if ever needed; crash containment, not a security boundary
    (`fefat_app.executor`)."""

    def run(
        self, spec: ExecutionSpec, report: ProgressReport, check: StopCheck = keep_running
    ) -> ExecutionResult:
        """Run `spec` within its limits, giving `report` each report of its progress as it comes
        and asking `check` whenever a second passes without one; how it ended, its result
        validated. What either raises stops the execution, with every process it started, and
        comes through."""
        ...

    def close(self) -> None:
        """End any process the executor keeps between executions, as the server stops."""
        ...


class LibraryIndex(Protocol):
    """The index of the saved features and strategies (step 5.2, ADR-0020): their version files
    stay the record, and the lists read the index (`fefat_app.library`)."""

    def refresh(self) -> None:
        """Index the versions saved since, by the app or a notebook; refused with
        `LibraryRefusedError` where the files are not as indexed."""
        ...

    def strategies(self) -> tuple[IndexedStrategy, ...]:
        """The saved strategies by name, each with its versions in order."""
        ...

    def features(self) -> tuple[IndexedFeature, ...]:
        """The saved features by name, each with its versions in order."""
        ...
