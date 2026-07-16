"""SQL-derived gauges for observability (worker lag, table/db sizes).

Fetch/outcome counters moved to OpenTelemetry (see app.telemetry); what remains here
are the live gauges computed by SQL at refresh time. None are user-scoped — these are
instance-wide ops signals. The API's gauge-refresh loop reads these and pushes them
into the OTel ObservableGauge cache.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Tables surfaced as size/row gauges (the ones whose growth we watch, DESIGN.md §2 r6).
_SIZE_TABLES = (
    "entries",
    "feeds",
    "subscriptions",
    "entry_states",
    "icons",
    "users",
    "api_tokens",
    "folders",
)


async def worker_lag_seconds(session: AsyncSession) -> float:
    """Age of the oldest feed that is due but unclaimed — the worker's backlog depth.
    Zero when nothing is waiting (the healthy steady state)."""
    value = await session.scalar(
        text(
            "SELECT COALESCE(EXTRACT(EPOCH FROM now() - min(next_check_at)), 0) "
            "FROM feeds WHERE next_check_at <= now() AND claimed_until < now()"
        )
    )
    return float(value or 0.0)


@dataclass(frozen=True)
class TableSize:
    table: str
    bytes: int
    rows: int


async def table_sizes(session: AsyncSession) -> list[TableSize]:
    """Per-table total size + approximate row count (reltuples, cheap at scale)."""
    rows = await session.execute(
        text(
            "SELECT c.relname AS table, pg_total_relation_size(c.oid) AS bytes, "
            "       GREATEST(c.reltuples, 0)::bigint AS rows "
            "  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            " WHERE n.nspname = 'public' AND c.relname = ANY(:tables)"
        ),
        {"tables": list(_SIZE_TABLES)},
    )
    return [TableSize(table=r.table, bytes=r.bytes, rows=r.rows) for r in rows]


async def db_size_bytes(session: AsyncSession) -> int:
    value = await session.scalar(text("SELECT pg_database_size(current_database())"))
    return int(value or 0)
