"""A revoked API token's name free for a new token (step 5.4, from `BACKLOG.md`): a token's name is
unique among the live tokens alone, an index over the rows not revoked in place of the table's
constraint, so that a password change, which revokes every token (step 5.2), uses up no name. The
downgrade gives the table its constraint again, which holds one row a name, so the revoked rows,
which no request reads, go first."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("api_tokens") as tokens:
        tokens.drop_constraint("uq_api_tokens_name", type_="unique")
        tokens.create_index(
            "ix_api_tokens_live_name",
            ["name"],
            unique=True,
            sqlite_where=sa.text("revoked_at IS NULL"),
        )


def downgrade() -> None:
    op.execute("DELETE FROM api_tokens WHERE revoked_at IS NOT NULL")
    with op.batch_alter_table("api_tokens") as tokens:
        tokens.drop_index("ix_api_tokens_live_name")
        tokens.create_unique_constraint("uq_api_tokens_name", ["name"])
