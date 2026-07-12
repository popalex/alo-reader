"""cross-process metric counters for /metrics (WP-15, DESIGN.md §1.4)

The worker and API are separate processes, so runtime counters the worker keeps
(fetch outcomes by class, per-host 403/429) can't be scraped from the API's memory.
This tiny table is the shared sink: the worker UPSERT-increments a row per event and
the API's /metrics reads them. Live gauges (worker lag, table sizes) are computed by
SQL at scrape time and need no storage. ``label`` holds the pre-formatted Prometheus
label content (e.g. ``class="new_body"``) so rendering is a trivial join.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE metric_counters (
            name  text   NOT NULL,
            label text   NOT NULL DEFAULT '',
            value bigint NOT NULL DEFAULT 0,
            PRIMARY KEY (name, label)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS metric_counters")
