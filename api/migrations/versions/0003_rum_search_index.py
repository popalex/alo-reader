"""rum index for index-ordered full-text search (WP-13 perf, DESIGN.md §4.1)

Core Postgres GIN finds full-text matches but returns them unordered, so the
chronological ``ORDER BY id DESC LIMIT 50`` has to sort the whole match set — the
p95 blows past the 100ms budget at scale (benchmarked ~166ms p95 at 5M). The RUM
extension stores ``id`` alongside the tsvector and returns matches already in id
order, so the query uses ``ORDER BY id <=| :anchor`` and never sorts (~35ms p95 at
5M, 5 cold runs). RUM supersedes the GIN for this table's one FTS use, so the GIN
is dropped. Requires the ``rum`` extension (see deploy/Dockerfile.postgres).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPGRADE_STATEMENTS: list[str] = [
    "CREATE EXTENSION IF NOT EXISTS rum",
    "DROP INDEX IF EXISTS idx_entries_fts",
    # addon opclass: the tsvector index carries `id` for ordered retrieval. The
    # WITH clause names the ordering attribute (id) attached to the tsvector.
    """
    CREATE INDEX idx_entries_rum ON entries
        USING rum (search_tsv rum_tsvector_addon_ops, id)
        WITH (attach = 'id', to = 'search_tsv')
    """,
]


DOWNGRADE_STATEMENTS: list[str] = [
    "DROP INDEX IF EXISTS idx_entries_rum",
    "CREATE INDEX idx_entries_fts ON entries USING GIN (search_tsv)",
    "DROP EXTENSION IF EXISTS rum",
]


def upgrade() -> None:
    for stmt in UPGRADE_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_STATEMENTS:
        op.execute(stmt)
