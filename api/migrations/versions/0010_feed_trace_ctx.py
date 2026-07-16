"""feeds.trace_ctx — propagate the triggering trace into the worker poll

When a subscribe or manual refresh queues a feed for an immediate poll, we stash the
request's W3C traceparent here. The worker continues that trace on the resulting poll
(then clears it), so a browser subscribe → API → worker fetch → parse → DB insert shows
as one end-to-end trace. NULL for scheduled polls (their own traces).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE feeds ADD COLUMN trace_ctx text")


def downgrade() -> None:
    op.execute("ALTER TABLE feeds DROP COLUMN IF EXISTS trace_ctx")
