"""entry summary preview column (code-review perf fix)

The stream-listing endpoint used to strip HTML out of every entry's ``content_html``
on every request (once per row) to build the list preview — CPU-bound work on the
event loop that scaled with page size and body length. This stores the plain-text
preview once, at ingest, so the read path just selects a column.

Existing rows are backfilled here with a set-based approximation using the in-DB
``strip_html`` function (tag-strip + whitespace-collapse). It doesn't decode HTML
entities the way the Python ``summarize`` does, but the summary is a cosmetic list
preview; every row written after this migration gets the exact Python summary.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Constant DEFAULT → metadata-only add on PG (no table rewrite).
    op.execute("ALTER TABLE entries ADD COLUMN summary text NOT NULL DEFAULT ''")
    # Backfill existing rows: strip tags, collapse whitespace, trim to ~300 chars.
    op.execute(
        r"""
        UPDATE entries e
           SET summary = CASE
                 WHEN char_length(t.txt) <= 300 THEN t.txt
                 ELSE btrim(left(t.txt, 300)) || '…'
               END
          FROM (
                SELECT id,
                       btrim(regexp_replace(strip_html(content_html), '\s+', ' ', 'g')) AS txt
                  FROM entries
               ) t
         WHERE e.id = t.id
           AND t.txt <> ''
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE entries DROP COLUMN IF EXISTS summary")
