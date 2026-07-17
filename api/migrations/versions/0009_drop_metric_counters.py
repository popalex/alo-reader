"""drop metric_counters (metrics moved to OpenTelemetry)

Fetch/outcome counters used to live in the ``metric_counters`` table, read back by the
hand-rolled ``/metrics`` endpoint. Metrics now go through OpenTelemetry (in-process
instruments exported to the collector), so the table and the DB write per fetch it
required are gone. Downgrade recreates the (empty) table from migration 0006.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS metric_counters")


def downgrade() -> None:
    op.execute("""
        CREATE TABLE metric_counters (
            name  text   NOT NULL,
            label text   NOT NULL DEFAULT '',
            value bigint NOT NULL DEFAULT 0,
            PRIMARY KEY (name, label)
        )
    """)
