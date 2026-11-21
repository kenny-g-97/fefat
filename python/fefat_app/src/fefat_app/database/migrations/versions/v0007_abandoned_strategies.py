"""A strategy's abandoned mark (step 5.5, D-29, D-109): `strategies.abandoned_json`, the mark its
folder's `abandoned.json` holds, where the strategy broke, the lesson, and when it was marked, or
null for a strategy not abandoned, which every indexing writes from the files as they stand
(ADR-0020). The mark stays whole in one column, so that no row holds half of one.

SQLite adds and drops the column in place: a batch migration's rebuild of `strategies`, which
`strategy_versions` refers to, drops the old table under rows that refer to it, which SQLite
counts against the commit whether the foreign keys are deferred or not."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("strategies", recreate="never") as strategies:
        strategies.add_column(sa.Column("abandoned_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("strategies", recreate="never") as strategies:
        strategies.drop_column("abandoned_json")
