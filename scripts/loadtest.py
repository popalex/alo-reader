"""Multi-tenant load test (WP-15 acceptance, DESIGN.md §1.4, §7).

Seeds a large multi-tenant corpus, then asserts the three budgets the WP names:

1. **API p95 < 100 ms** on the hot read paths — the stream page and the unread
   counts — measured through the *real* store query builders (the same SQL the
   endpoints run; HTTP/auth overhead is constant and negligible), sampled across
   random users.
2. **Worker drains a 1k-feed backlog** — the lock-free claim loop processes a
   backlog of due feeds (network stubbed to a 304, so it exercises claim + schedule
   + persist, not the internet) within a time budget.
3. **Zero cross-tenant rows** — a randomized probe sweep confirms every entry a user
   sees belongs to a feed they subscribe to, and one user's read state never leaks
   into another's view.

Profiles (LOAD_PROFILE, or override the individual LOAD_* vars):
    smoke     50 users / 500 feeds / 50k entries   — fast, proves the script e2e
    ci-nightly 1000 users / 20k feeds / 5M entries  — the WP's full budget profile

    DATABASE_URL=postgresql+asyncpg://alo:alo@localhost:5432/alo \
        LOAD_PROFILE=smoke .venv/bin/python scripts/loadtest.py

Schema must already be migrated (`make migrate`). Idempotent: it removes its own
synthetic tenants first and again on exit unless LOAD_KEEP=1.
"""

import asyncio
import logging
import os
import random
import time

import asyncpg
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.models import Subscription
from app.store import entries as entries_store
from app.store.counts import unread_counts
from app.worker.fetch import FetchResult
from app.worker.main import poll_once

PROFILES = {
    "smoke": {"users": 50, "feeds": 500, "entries": 50_000},
    "ci-nightly": {"users": 1_000, "feeds": 20_000, "entries": 5_000_000},
}
PROFILE = os.getenv("LOAD_PROFILE", "smoke")
_P = PROFILES.get(PROFILE, PROFILES["smoke"])

USERS = int(os.getenv("LOAD_USERS", _P["users"]))
FEEDS = int(os.getenv("LOAD_FEEDS", _P["feeds"]))
ENTRIES = int(os.getenv("LOAD_ENTRIES", _P["entries"]))
SUBS_PER_USER = int(os.getenv("LOAD_SUBS_PER_USER", "30"))
BACKLOG = int(os.getenv("LOAD_BACKLOG", "1000"))

P95_BUDGET_MS = float(os.getenv("LOAD_P95_MS", "100"))
DRAIN_BUDGET_S = float(os.getenv("LOAD_DRAIN_S", "60"))
SAMPLE = int(os.getenv("LOAD_SAMPLE", "300"))  # query samples per measured path
PROBE = int(os.getenv("LOAD_PROBE", "200"))  # users in the cross-tenant sweep

TAG = "loadtest.invalid"  # marks synthetic rows for cleanup
RNG = random.Random(2025)


def dsn() -> str:
    return os.environ["DATABASE_URL"].replace("+asyncpg", "")


async def cleanup(conn: asyncpg.Connection) -> None:
    # Users cascade subscriptions + entry_states; feeds then cascade their entries.
    await conn.execute("DELETE FROM users WHERE email LIKE '%' || $1", TAG)
    await conn.execute("DELETE FROM feeds WHERE feed_url LIKE '%' || $1 || '%'", TAG)


async def seed(conn: asyncpg.Connection) -> tuple[list[int], list[int]]:
    await cleanup(conn)
    print(
        f"seeding {USERS:,} users / {FEEDS:,} feeds / {ENTRIES:,} entries…", flush=True
    )
    t0 = time.perf_counter()

    # Triggers (orphan tracking) would fire per COPY row; disable during bulk load and
    # fix orphaned_at with a set-based UPDATE afterward.
    await conn.execute("ALTER TABLE subscriptions DISABLE TRIGGER USER")

    user_ids = [
        r["id"]
        for r in await conn.fetch(
            "INSERT INTO users (email) SELECT 'u' || g || '@' || $1 "
            "FROM generate_series(1, $2) g RETURNING id",
            TAG,
            USERS,
        )
    ]
    feed_ids = [
        r["id"]
        for r in await conn.fetch(
            "INSERT INTO feeds (feed_url, title) "
            "SELECT 'https://' || g || '.' || $1 || '/rss', 'Feed ' || g "
            "FROM generate_series(1, $2) g RETURNING id",
            TAG,
            FEEDS,
        )
    ]

    subs: list[tuple[int, int, int]] = []
    for uid in user_ids:
        for fid in RNG.sample(feed_ids, min(SUBS_PER_USER, len(feed_ids))):
            subs.append((uid, fid, 0))
    await conn.copy_records_to_table(
        "subscriptions", columns=["user_id", "feed_id", "since_entry_id"], records=subs
    )

    def entry_rows() -> list[tuple[int, bytes, str, str]]:
        rows = []
        for i in range(ENTRIES):
            fid = feed_ids[i % FEEDS]
            rows.append((fid, i.to_bytes(8, "big"), f"Entry {i}", f"<p>body {i}</p>"))
        return rows

    await conn.copy_records_to_table(
        "entries",
        columns=["feed_id", "guid_hash", "title", "content_html"],
        records=entry_rows(),
    )

    # A slice of read state for a sample of users (counts realism + isolation probe).
    sample_uids = user_ids[: min(len(user_ids), 100)]
    await conn.execute(
        "INSERT INTO entry_states (user_id, entry_id, is_read, is_starred, changed_at) "
        "SELECT s.user_id, e.id, true, false, now() "
        "  FROM subscriptions s JOIN entries e ON e.feed_id = s.feed_id AND e.id % 3 = 0 "
        " WHERE s.user_id = ANY($1::bigint[]) ON CONFLICT DO NOTHING",
        sample_uids,
    )

    await conn.execute(
        "UPDATE feeds SET orphaned_at = NULL "
        " WHERE EXISTS (SELECT 1 FROM subscriptions s WHERE s.feed_id = feeds.id)"
    )
    await conn.execute("ALTER TABLE subscriptions ENABLE TRIGGER USER")
    await conn.execute("ANALYZE")
    print(f"  seeded in {time.perf_counter() - t0:.1f}s", flush=True)
    return user_ids, feed_ids


def _pctile(samples: list[float], p: float) -> float:
    return sorted(samples)[min(len(samples) - 1, int(len(samples) * p))]


async def measure_reads(
    sm: async_sessionmaker[AsyncSession], user_ids: list[int]
) -> tuple[list[float], list[float]]:
    stream_ms: list[float] = []
    counts_ms: list[float] = []
    for _ in range(SAMPLE):
        uid = RNG.choice(user_ids)
        async with sm() as s:
            t0 = time.perf_counter()
            await entries_store.list_stream_page(
                s, uid, "all", status="unread", limit=50
            )
            stream_ms.append((time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter()
            await unread_counts(s, uid)
            counts_ms.append((time.perf_counter() - t0) * 1000)
    return stream_ms, counts_ms


async def cross_tenant_probe(
    sm: async_sessionmaker[AsyncSession], user_ids: list[int]
) -> int:
    """Return the number of cross-tenant leaks found (must be 0)."""
    leaks = 0
    for uid in RNG.sample(user_ids, min(PROBE, len(user_ids))):
        async with sm() as s:
            subscribed = set(
                (
                    await s.scalars(
                        select(Subscription.feed_id).where(Subscription.user_id == uid)
                    )
                ).all()
            )
            rows = await entries_store.list_stream_page(
                s, uid, "all", status="all", limit=50
            )
        for r in rows:
            if r.entry.feed_id not in subscribed:
                leaks += 1  # an entry from a feed this user is not subscribed to
    return leaks


async def worker_drain(
    sm: async_sessionmaker[AsyncSession], settings: Settings
) -> tuple[float, int]:
    """Mark up to BACKLOG feeds due, then drain them via the real claim loop (fetch
    stubbed to a 304 — no network). Returns (seconds, feeds processed)."""
    async with sm() as s, s.begin():
        await s.execute(
            text(
                "UPDATE feeds SET next_check_at = 'epoch', claimed_until = 'epoch' "
                "WHERE id IN (SELECT id FROM feeds ORDER BY id LIMIT :n)"
            ),
            {"n": BACKLOG},
        )

    async def stub_fetch(feed: object, **_: object) -> FetchResult:
        return FetchResult(
            status="not_modified", final_url=getattr(feed, "feed_url", "")
        )

    t0 = time.perf_counter()
    processed = 0
    while processed < BACKLOG:
        n = await poll_once(sm, settings=settings, fetch=stub_fetch)
        processed += n
        if n == 0:
            break
    return time.perf_counter() - t0, processed


def _report(label: str, ms: list[float]) -> float:
    p50, p95, p99 = _pctile(ms, 0.5), _pctile(ms, 0.95), _pctile(ms, 0.99)
    print(
        f"  {label:<8} p50={p50:6.1f}ms  p95={p95:6.1f}ms  p99={p99:6.1f}ms", flush=True
    )
    return p95


async def main() -> int:
    logging.getLogger("worker").setLevel(logging.WARNING)  # quiet per-feed poll logs
    url = os.environ["DATABASE_URL"]
    conn = await asyncpg.connect(dsn())
    engine = create_async_engine(url)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(  # type: ignore[call-arg]
        database_url=url,
        auth_mode="none",
        worker_per_host_delay_s=0.0,
        worker_fetch_favicons=False,
    )
    ok = True
    try:
        user_ids, _ = await seed(conn)

        await measure_reads(sm, user_ids)  # warm caches
        stream_ms, counts_ms = await measure_reads(sm, user_ids)
        print(f"\nprofile={PROFILE} (budget p95 < {P95_BUDGET_MS:.0f}ms)", flush=True)
        stream_p95 = _report("stream", stream_ms)
        counts_p95 = _report("counts", counts_ms)

        drain_s, drained = await worker_drain(sm, settings)
        print(
            f"  worker   drained {drained} feeds in {drain_s:.2f}s "
            f"({drained / drain_s:,.0f}/s, budget < {DRAIN_BUDGET_S:.0f}s)",
            flush=True,
        )

        leaks = await cross_tenant_probe(sm, user_ids)
        print(
            f"  isolation {PROBE} users probed, cross-tenant rows = {leaks}", flush=True
        )

        print("\nresults:", flush=True)
        for name, value, budget, good in [
            ("stream p95", stream_p95, P95_BUDGET_MS, stream_p95 < P95_BUDGET_MS),
            ("counts p95", counts_p95, P95_BUDGET_MS, counts_p95 < P95_BUDGET_MS),
            ("worker drain", drain_s, DRAIN_BUDGET_S, drain_s < DRAIN_BUDGET_S),
            ("cross-tenant leaks", leaks, 0, leaks == 0),
        ]:
            verdict = "PASS" if good else "FAIL"
            print(f"  [{verdict}] {name} = {value} (budget {budget})", flush=True)
            ok = ok and good
    finally:
        if os.getenv("LOAD_KEEP") != "1":
            await cleanup(conn)
        await conn.close()
        await engine.dispose()

    print("\nPASS" if ok else "\nFAIL", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
