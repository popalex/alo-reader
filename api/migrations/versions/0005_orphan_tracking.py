"""orphan-feed tracking for the GC job (WP-15, DESIGN.md §1.3 GC, §0.3)

A globally-deduped feed with zero subscribers is dead weight and gets garbage-
collected after a grace period. To know *how long* it has had no subscribers we
stamp ``feeds.orphaned_at`` when the last subscription goes away and clear it when
one comes back — maintained by a trigger so it is correct even when subscriptions
disappear via a cascade (e.g. account deletion), not only the API delete path.

New feeds default to orphaned_at = now(): a feed created but never subscribed (a
failed subscribe) is still reclaimed after the grace period rather than leaking.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


UPGRADE_STATEMENTS: list[str] = [
    "ALTER TABLE feeds ADD COLUMN orphaned_at timestamptz DEFAULT now()",
    # Existing feeds with subscribers are not orphaned.
    """
    UPDATE feeds SET orphaned_at = NULL
     WHERE EXISTS (SELECT 1 FROM subscriptions s WHERE s.feed_id = feeds.id)
    """,
    # Partial index: the GC only ever scans the orphaned rows.
    "CREATE INDEX idx_feeds_orphaned ON feeds (orphaned_at) WHERE orphaned_at IS NOT NULL",
    """
    CREATE OR REPLACE FUNCTION feeds_track_orphan() RETURNS trigger AS $$
    BEGIN
      IF TG_OP = 'INSERT' THEN
        UPDATE feeds SET orphaned_at = NULL WHERE id = NEW.feed_id;
        RETURN NEW;
      ELSE
        UPDATE feeds SET orphaned_at = now()
         WHERE id = OLD.feed_id
           AND NOT EXISTS (SELECT 1 FROM subscriptions WHERE feed_id = OLD.feed_id);
        RETURN OLD;
      END IF;
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER trg_subs_orphan_ins AFTER INSERT ON subscriptions
        FOR EACH ROW EXECUTE FUNCTION feeds_track_orphan()
    """,
    """
    CREATE TRIGGER trg_subs_orphan_del AFTER DELETE ON subscriptions
        FOR EACH ROW EXECUTE FUNCTION feeds_track_orphan()
    """,
]


DOWNGRADE_STATEMENTS: list[str] = [
    "DROP TRIGGER IF EXISTS trg_subs_orphan_del ON subscriptions",
    "DROP TRIGGER IF EXISTS trg_subs_orphan_ins ON subscriptions",
    "DROP FUNCTION IF EXISTS feeds_track_orphan()",
    "DROP INDEX IF EXISTS idx_feeds_orphaned",
    "ALTER TABLE feeds DROP COLUMN IF EXISTS orphaned_at",
]


def upgrade() -> None:
    for stmt in UPGRADE_STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in DOWNGRADE_STATEMENTS:
        op.execute(stmt)
