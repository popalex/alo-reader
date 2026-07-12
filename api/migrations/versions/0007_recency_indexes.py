"""recency-ordering indexes for the stream listing

Operator decision (overrides the original id-only ordering): the stream listing now
orders by ``COALESCE(published_at, created_at) DESC, id DESC`` so a feed's own publish
date drives the order rather than ingest/id order. These expression indexes back that
ORDER BY + keyset cursor: one global (all / folder / starred sort across feeds) and one
feed-scoped (a single feed's stream). Search is unaffected — it stays on the rum index.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX idx_entries_recency ON entries "
        "((COALESCE(published_at, created_at)) DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX idx_entries_feed_recency ON entries "
        "(feed_id, (COALESCE(published_at, created_at)) DESC, id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_entries_feed_recency")
    op.execute("DROP INDEX IF EXISTS idx_entries_recency")
