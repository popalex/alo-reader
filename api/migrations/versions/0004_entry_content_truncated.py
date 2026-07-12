"""entry content-cap flag (WP-15, DESIGN.md §1.4 cost ceilings)

The content cap (store the first ~500 KB of sanitized HTML) truncates oversized
bodies; this column flags an entry whose content was cut so the UI can show a
"truncated — open original" affordance instead of silently misleading the reader.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE entries ADD COLUMN content_truncated boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE entries DROP COLUMN IF EXISTS content_truncated")
