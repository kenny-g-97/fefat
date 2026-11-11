"""The index of the strategies' versions (step 5.2, D-93, D-84): the strategies by their names, each
saved version as its file `strategies/<name>/v<n>.json` keeps it (`fefat.strategy.versions`),
and the feature versions each version pins; and triggers that refuse an update or a delete of a
version's row or of a pin's (D-11, ADR-0020). A strategy's row is not guarded, since step 5.5
writes its abandoned mark into it (migration `0006`)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX_TABLES = ("strategy_versions", "strategy_version_features")
"""The tables whose rows index a file, never updated or deleted."""


def upgrade() -> None:
    op.create_table(
        "strategies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.UniqueConstraint("workspace_id", "name"),
    )
    op.create_table(
        "strategy_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("strategy_id", sa.String(36), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("instrument", sa.String(), nullable=False),
        sa.Column("timeframe", sa.String(), nullable=False),
        sa.Column("params_schema_json", sa.JSON(), nullable=False),
        sa.Column("changelog", sa.Text(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"]),
        sa.UniqueConstraint("strategy_id", "version_no"),
        sa.UniqueConstraint("strategy_id", "content_hash"),
    )
    op.create_table(
        "strategy_version_features",
        sa.Column("strategy_version_id", sa.String(36), nullable=False),
        sa.Column("feature_version_id", sa.String(36), nullable=False),
        _created_at(),
        sa.PrimaryKeyConstraint("strategy_version_id", "feature_version_id"),
        sa.ForeignKeyConstraint(["strategy_version_id"], ["strategy_versions.id"]),
        sa.ForeignKeyConstraint(["feature_version_id"], ["feature_versions.id"]),
    )
    for table in INDEX_TABLES:
        for statement, refused in (("UPDATE", "updated"), ("DELETE", "deleted")):
            op.execute(
                f"CREATE TRIGGER {table}_no_{statement.lower()} BEFORE {statement} ON {table} "
                f"BEGIN SELECT RAISE(ABORT, '{table} rows are never {refused} (ADR-0020)'); END"
            )


def downgrade() -> None:
    for table in ("strategy_version_features", "strategy_versions", "strategies"):
        op.drop_table(table)


def _created_at() -> sa.Column[str]:
    return sa.Column("created_at", sa.String(), nullable=False)
