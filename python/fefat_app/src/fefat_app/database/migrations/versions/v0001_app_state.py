"""The app's state and the index of the workspace's files (step 4.1, D-83, D-84, D-85): the
settings, the workspaces, the features with their versions, the leak detector's reports, the
saved import profiles, the jobs, and their events; and triggers that refuse an update or a
delete of a row that indexes a file (D-11, ADR-0020)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_TABLES = ("feature_versions", "feature_validations", "import_profiles")
"""The tables whose rows index a file, never updated or deleted."""


def upgrade() -> None:
    _settings_and_workspaces()
    _features()
    _import_profiles()
    _jobs_and_events()
    for table in INDEX_TABLES:
        for statement, refused in (("UPDATE", "updated"), ("DELETE", "deleted")):
            op.execute(
                f"CREATE TRIGGER {table}_no_{statement.lower()} BEFORE {statement} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} rows are never {refused} (ADR-0020)'); END"
            )


def downgrade() -> None:
    for table in (
        "events",
        "jobs",
        "import_profiles",
        "feature_validations",
        "feature_versions",
        "features",
        "workspaces",
        "settings",
    ):
        op.drop_table(table)


def _created_at() -> sa.Column[str]:
    return sa.Column("created_at", sa.String(), nullable=False)


def _settings_and_workspaces() -> None:
    op.create_table(
        "settings",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value_json", sa.JSON(), nullable=False),
        _created_at(),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("name"),
    )


def _features() -> None:
    op.create_table(
        "features",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.UniqueConstraint("workspace_id", "name"),
    )
    op.create_table(
        "feature_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("feature_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("params_schema_json", sa.JSON(), nullable=False),
        sa.Column("inputs_json", sa.JSON(), nullable=False),
        sa.Column("outputs_json", sa.JSON(), nullable=False),
        sa.Column("warmup", sa.JSON(), nullable=False),
        sa.Column("warmup_sessions", sa.JSON(), nullable=False),
        sa.Column("combination_json", sa.JSON(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(["feature_id"], ["features.id"]),
        sa.UniqueConstraint("feature_id", "version_no"),
        sa.UniqueConstraint("feature_id", "content_hash"),
    )
    op.create_table(
        "feature_validations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("feature_version_id", sa.String(36), nullable=True),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("feature_name", sa.String(), nullable=False),
        sa.Column("feature_hash", sa.String(64), nullable=False),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["feature_version_id"], ["feature_versions.id"]),
        sa.UniqueConstraint("report_sha256"),
    )


def _import_profiles() -> None:
    op.create_table(
        "import_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        _created_at(),
        sa.UniqueConstraint("sha256"),
    )


def _jobs_and_events() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("worker_pid", sa.Integer(), nullable=True),
        sa.Column("lease_expires_at", sa.String(), nullable=True),
        sa.Column("cancel_requested_at", sa.String(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("finished_at", sa.String(), nullable=True),
        _created_at(),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stream_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=False),
        _created_at(),
        sqlite_autoincrement=True,
    )
