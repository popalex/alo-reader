"""Store functions backing /metrics (WP-15, DESIGN.md §1.4).

Two kinds of data: cumulative counters the worker increments in ``metric_counters``
(read back verbatim), and live gauges computed by SQL at scrape time (worker lag,
table sizes/rows, DB size). None are user-scoped — these are instance-wide ops
signals, not user data.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import label_str

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

_INCR_SQL = text("""
    INSERT INTO metric_counters (name, label, value) VALUES (:name, :label, :by)
    ON CONFLICT (name, label) DO UPDATE SET value = metric_counters.value + :by
""")


async def incr(session: AsyncSession, name: str, *, label: str = "", by: int = 1) -> None:
    await session.execute(_INCR_SQL, {"name": name, "label": label, "by": by})


# Metric names (shared by the recorder and the /metrics renderer).
FETCH_OUTCOMES = "alo_fetch_outcomes_total"
FETCH_HOST_RESPONSES = "alo_fetch_host_responses_total"


async def record_fetch(
    session: AsyncSession, *, host: str, outcome: str, http_status: int | None
) -> None:
    """Count one feed fetch by outcome class, plus per-host 403/429 (DESIGN.md §2 r5)."""
    await incr(session, FETCH_OUTCOMES, label=label_str([("class", outcome)]))
    if http_status in (403, 429):
        await incr(
            session,
            FETCH_HOST_RESPONSES,
            label=label_str([("host", host or "?"), ("code", str(http_status))]),
        )


@dataclass(frozen=True)
class Counter:
    name: str
    label: str
    value: int


async def all_counters(session: AsyncSession) -> list[Counter]:
    rows = await session.execute(
        text("SELECT name, label, value FROM metric_counters ORDER BY name, label")
    )
    return [Counter(name=r.name, label=r.label, value=r.value) for r in rows]


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
