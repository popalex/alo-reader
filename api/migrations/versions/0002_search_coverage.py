"""search coverage: author + feed name (WP-13, DESIGN.md §4.1)

Widens what a query matches beyond title + content:

- ``entries.search_tsv`` gains ``author`` (weight C — distinct so a future ranked
  mode can weight it below the title/body). Regenerating a STORED generated column
  means dropping and re-adding it, which recomputes every row and recreates the GIN.
- Feed name can't live in ``entries.search_tsv`` (a generated column can't read
  another table), so ``feeds`` gets its own ``search_tsv`` + GIN. The search query
  matches a feed name via ``entries.feed_id IN (SELECT id FROM feeds WHERE …)`` — both
  branches then sit on ``entries`` so Postgres can BitmapOr the GIN and the
  ``(feed_id, id DESC)`` index rather than fall back to a seq scan.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPGRADE_STATEMENTS: list[str] = [
    # Rebuild entries.search_tsv with author (weight C). Dropping the column also
    # drops idx_entries_fts; both are recreated below.
    "ALTER TABLE entries DROP COLUMN search_tsv",
    """
    ALTER TABLE entries ADD COLUMN search_tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english'::regconfig, coalesce(title, '')), 'A')
        || setweight(to_tsvector('english'::regconfig, coalesce(author, '')), 'C')
        || setweight(
             to_tsvector('english'::regconfig,
                         left(strip_html(content_html), 20000)), 'B')
    ) STORED
    """,
    "CREATE INDEX idx_entries_fts ON entries USING GIN (search_tsv)",
    # Feed-name index: a small generated tsvector on the (few) feed rows.
    """
    ALTER TABLE feeds ADD COLUMN search_tsv tsvector GENERATED ALWAYS AS (
        to_tsvector('english'::regconfig, coalesce(title, ''))
    ) STORED
    """,
    "CREATE INDEX idx_feeds_fts ON feeds USING GIN (search_tsv)",
]


DOWNGRADE_STATEMENTS: list[str] = [
    "DROP INDEX IF EXISTS idx_feeds_fts",
    "ALTER TABLE feeds DROP COLUMN IF EXISTS search_tsv",
    "DROP INDEX IF EXISTS idx_entries_fts",
    "ALTER TABLE entries DROP COLUMN search_tsv",
    """
    ALTER TABLE entries ADD COLUMN search_tsv tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english'::regconfig, coalesce(title, '')), 'A')
        || setweight(
             to_tsvector('english'::regconfig,
                         left(strip_html(content_html), 20000)), 'B')
    ) STORED
    """,
    "CREATE INDEX idx_entries_fts ON entries USING GIN (search_tsv)",
]


def upgrade() -> None:
    for stmt in UPGRADE_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_STATEMENTS:
        op.execute(stmt)
