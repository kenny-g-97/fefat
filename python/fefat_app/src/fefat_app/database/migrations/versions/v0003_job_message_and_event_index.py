"""A job's last progress message, which the list of jobs shows without reading their streams, and
an index of the events by stream and id, which a stream's reader asks for after the last event
it saw (step 4.4, D-90)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as jobs:
        jobs.add_column(sa.Column("message", sa.Text(), nullable=True))
    op.create_index("ix_events_stream_id_id", "events", ["stream_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_events_stream_id_id", table_name="events")
    with op.batch_alter_table("jobs") as jobs:
        jobs.drop_column("message")
