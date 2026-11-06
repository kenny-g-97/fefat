"""The app's tables (`01-architecture.md` section 5, D-83, D-84, D-85, D-86): its own state, the
settings it edits, the workspaces, the login sessions, the API tokens, the jobs, and their
events; and an index of the workspace's
files, the feature versions, the leak detector's reports, and the saved import profiles, which
stay the record (ADR-0020). The migrations under `migrations/` make them, and a test holds the
two alike.

Every id is a UUIDv7 (`fefat_app.database.uuid7`) but an event's, which counts up, since a
stream's reader resumes after the last event it saw (`01` section 6). Every row carries
`created_at`, an instant in UTC. A row that indexes a file is never updated or deleted, which
triggers of the migrations enforce (D-11)."""

import enum
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Dialect,
    Enum,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from fefat.market.importers.profiles import ProfileKind
from fefat_app.database.uuid7 import new_uuid7

ID = String(36)
"""A UUIDv7 as text."""
SHA256 = String(64)
"""A SHA-256 as 64 hexadecimal digits."""


class UtcInstant(TypeDecorator[datetime]):
    """An aware instant, kept as ISO 8601 text in UTC to the microsecond, which sorts in time
    order; a naive one is refused."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(f"Expected an aware instant, got the naive {value.isoformat()}.")
        return value.astimezone(UTC).isoformat(timespec="microseconds")

    def process_result_value(self, value: str | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)


def _now() -> datetime:
    return datetime.now(UTC)


def _values(members: type[enum.Enum]) -> list[str]:
    """The values an enum's column keeps, rather than its members' names."""
    return [member.value for member in members]


class Base(DeclarativeBase):
    """The tables' metadata, whose convention names every constraint, as Alembic's batch mode
    needs to rebuild a SQLite table."""

    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
        }
    )


class SettingRow(Base):
    """A setting the app edits, such as the password's hash or the theme, by its key (D-83);
    what the server needs before the database opens is in `config.toml` (`fefat.config`)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[Any] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcInstant, default=_now)


class WorkspaceRow(Base):
    """A workspace by its name, with its folder under `FEFAT_HOME`; the first release has one,
    `default` (`01-architecture.md` section 4)."""

    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_uuid7)
    name: Mapped[str] = mapped_column(String, unique=True)
    path: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcInstant, default=_now)


class LoginSessionRow(Base):
    """A login session (step 4.2, D-86) by the SHA-256 of the token its cookie carries, never the
    token itself, with when it ends and when it was last seen. The glossary's session is a
    trading session, so the code says login session; the table keeps `01` section 5's name."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_uuid7)
    token_hash: Mapped[str] = mapped_column(SHA256, unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcInstant, default=_now)
    expires_at: Mapped[datetime] = mapped_column(UtcInstant)
    last_seen_at: Mapped[datetime] = mapped_column(UtcInstant)


class ApiTokenRow(Base):
    """An API token of a notebook or a script (step 4.2, D-86) by its name, with the SHA-256 of
    the token, never the token itself, when it was last used, and when it was revoked."""

    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_uuid7)
    name: Mapped[str] = mapped_column(String, unique=True)
    token_hash: Mapped[str] = mapped_column(SHA256, unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcInstant, default=_now)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcInstant)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcInstant)


class FeatureRow(Base):
    """A saved feature by its name in a workspace; its latest version is its highest number."""

    __tablename__ = "features"
    __table_args__ = (UniqueConstraint("workspace_id", "name"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_uuid7)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UtcInstant, default=_now)


class FeatureVersionRow(Base):
    """A saved version as its file `features/<name>/v<n>.json` keeps it
    (`fefat.features.FeatureVersion`): its number, its content hash (D-71), its code, its
    parameter schema, its inputs and outputs, its warm-ups in bars and in sessions, each a
    number or the lambda its decorator writes, a combination's description (step 3.7), and when
    it was saved."""

    __tablename__ = "feature_versions"
    __table_args__ = (
        UniqueConstraint("feature_id", "version_no"),
        UniqueConstraint("feature_id", "content_hash"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_uuid7)
    feature_id: Mapped[str] = mapped_column(ForeignKey("features.id"))
    version_no: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(SHA256)
    code: Mapped[str] = mapped_column(Text)
    params_schema_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    inputs_json: Mapped[list[Any]] = mapped_column(JSON)
    outputs_json: Mapped[dict[str, str]] = mapped_column(JSON)
    warmup: Mapped[int | str] = mapped_column(JSON)
    warmup_sessions: Mapped[int | str] = mapped_column(JSON)
    combination_json: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    created_at: Mapped[datetime] = mapped_column(UtcInstant, default=_now)


class FeatureValidationRow(Base):
    """A leak detector's report as its file `features/<name>/validations/<hash>.json` held it
    when indexed (`fefat.features.ValidationReport`), by the file's SHA-256: the file keeps only
    the latest report of its feature's hash, the index every report it saw (D-84). It names the
    feature and the hash it validated, and links the saved version of that hash where one was
    saved when the report was indexed; a link left empty stays empty."""

    __tablename__ = "feature_validations"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_uuid7)
    feature_version_id: Mapped[str | None] = mapped_column(ForeignKey("feature_versions.id"))
    report_sha256: Mapped[str] = mapped_column(SHA256, unique=True)
    feature_name: Mapped[str] = mapped_column(String)
    feature_hash: Mapped[str] = mapped_column(SHA256)
    instrument: Mapped[str] = mapped_column(String)
    timeframe: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    parameters_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UtcInstant, default=_now)


class ImportProfileRow(Base):
    """An import profile a trader saved, `profiles/<name>.yaml`
    (`fefat.market.importers.profiles`), by its file's SHA-256, with its kind and name."""

    __tablename__ = "import_profiles"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_uuid7)
    kind: Mapped[ProfileKind] = mapped_column(
        Enum(ProfileKind, native_enum=False, length=16, values_callable=_values)
    )
    name: Mapped[str] = mapped_column(String)
    sha256: Mapped[str] = mapped_column(SHA256, unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcInstant, default=_now)


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
    four ends, each change a compare-and-set update (step 4.4)."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class JobRow(Base):
    """A job of the app's process pool (`01-architecture.md` section 6), which step 4.4 runs."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(ID, primary_key=True, default=new_uuid7)
    kind: Mapped[JobKind] = mapped_column(
        Enum(JobKind, native_enum=False, length=32, values_callable=_values)
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, native_enum=False, length=16, values_callable=_values)
    )
    progress: Mapped[float] = mapped_column(Float)
    attempt: Mapped[int] = mapped_column(Integer)
    max_attempts: Mapped[int] = mapped_column(Integer)
    worker_pid: Mapped[int | None] = mapped_column(Integer)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UtcInstant)
    cancel_requested_at: Mapped[datetime | None] = mapped_column(UtcInstant)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON(none_as_null=True))
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(UtcInstant)
    finished_at: Mapped[datetime | None] = mapped_column(UtcInstant)
    created_at: Mapped[datetime] = mapped_column(UtcInstant, default=_now)


class EventRow(Base):
    """An event of a stream, such as `job:<id>`, a job's progress (`01-architecture.md` section
    6): its id counts up and is never reused, since a reader resumes after the last it saw."""

    __tablename__ = "events"
    __table_args__ = ({"sqlite_autoincrement": True},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stream_id: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column("type", String)
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcInstant, default=_now)
