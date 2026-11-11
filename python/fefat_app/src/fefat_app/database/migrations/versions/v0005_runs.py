"""The runs (step 5.3, D-93, D-84): a row for each backtest asked for through the API, with its
job until its folder `runs/<run key>/` is saved, and for each saved folder the index found, its
record's settings, metrics, fidelity eras, and warnings in its columns; a row holds its job or its
run key, and triggers refuse an update or a delete of a row once its run key is set (D-11,
ADR-0020), while a submission's row takes its key once, and one whose job's run proved saved
under another row's key is removed."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("strategy_version_id", sa.String(36), nullable=True),
        sa.Column("parameters_json", sa.JSON(), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=False),
        sa.Column("request_key", sa.String(64), nullable=True),
        sa.Column("job_id", sa.String(36), nullable=True),
        sa.Column("run_key", sa.String(64), nullable=True),
        sa.Column("metrics_json", sa.JSON(), nullable=True),
        sa.Column("fidelity_eras_json", sa.JSON(), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["strategy_version_id"], ["strategy_versions.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.UniqueConstraint("run_key"),
        sa.CheckConstraint(
            "job_id IS NOT NULL OR run_key IS NOT NULL", name="ck_runs_job_or_run_key"
        ),
    )
    op.create_index("ix_runs_request_key", "runs", ["request_key"])
    for statement, refused in (("UPDATE", "updated"), ("DELETE", "deleted")):
        op.execute(
            f"CREATE TRIGGER runs_no_{statement.lower()} BEFORE {statement} ON runs "
            "WHEN OLD.run_key IS NOT NULL "
            f"BEGIN SELECT RAISE(ABORT, 'runs rows are never {refused} once saved (ADR-0020)'); END"
        )


def downgrade() -> None:
    op.drop_table("runs")
