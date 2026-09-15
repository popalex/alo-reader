"""deleted_clerk_users — tombstones so a retried webhook cannot resurrect an account

svix retries a failed delivery for up to a day and does not guarantee ordering, so a
user.created can arrive after the user.deleted that removed the row. Without a record
of the deletion the handler cannot tell that from a first delivery, and it rebuilds the
local identity of an account that no longer exists.

Clerk user ids are never reused, so a tombstone is permanent for that id. The worker's
maintenance sweep drops rows older than the retry window.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE deleted_clerk_users (
            clerk_user_id text PRIMARY KEY,
            deleted_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_deleted_clerk_users_deleted_at ON deleted_clerk_users (deleted_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS deleted_clerk_users")
