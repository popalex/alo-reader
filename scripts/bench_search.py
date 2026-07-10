"""Search latency benchmark (WP-13 acceptance, DESIGN.md §4.1.6).

Seeds a large synthetic corpus into one feed, then times the search query shape
the API uses on its common path (websearch_to_tsquery against search_tsv, ordered
by the rum index via ``id <=| anchor``, LIMIT 50, ts_headline on the page) and
asserts the p95 stays under the budget.

Profiles (BENCH_PROFILE, or override with BENCH_ENTRIES):
    pr       100k entries   — per-PR gate (fast enough for CI)
    nightly  5M  entries    — nightly stress

    DATABASE_URL=postgresql+asyncpg://alo:alo@localhost:5432/alo \
        BENCH_PROFILE=pr .venv/bin/python scripts/bench_search.py

The schema must already be migrated (`make migrate`). Idempotent: it removes its
own bench user/feed first, and does the same on exit unless BENCH_KEEP=1.
"""

import asyncio
import os
import random
import statistics
import sys
import time

import asyncpg

PROFILES = {"pr": 100_000, "nightly": 5_000_000}
PROFILE = os.getenv("BENCH_PROFILE", "pr")
N = int(os.getenv("BENCH_ENTRIES", PROFILES.get(PROFILE, PROFILES["pr"])))
P95_BUDGET_MS = float(os.getenv("BENCH_P95_MS", "100"))
ITERATIONS = int(os.getenv("BENCH_ITERATIONS", "300"))

BENCH_EMAIL = "bench-search@example.invalid"
BENCH_FEED_URL = "https://bench-search.example.invalid/rss"

VOCAB_SIZE = 2000
WORDS_PER_DOC = 30
VOCAB = [f"term{i:04d}" for i in range(VOCAB_SIZE)]

# The common-path search shape from store.entries.search_stream_page, stream=all:
# pure FTS ordered by the rum index (id <=| anchor), no sort. The rum index comes
# from migration 0003 (needs the rum extension; see deploy/Dockerfile.postgres).
# $3 is the anchor (max id); the feed-name arm is resolved separately in the store
# and only appears when a feed title matches, so it's off this hot path.
SEARCH_SQL = """
SELECT e.id,
       ts_headline('english'::regconfig, left(strip_html(e.content_html), 20000), q,
                   'StartSel=<b>, StopSel=</b>, MaxWords=32, MinWords=12, MaxFragments=2')
FROM entries e
JOIN subscriptions s ON s.feed_id = e.feed_id AND s.user_id = $2
LEFT JOIN entry_states st ON st.entry_id = e.id AND st.user_id = $2
JOIN feeds f ON f.id = e.feed_id,
     websearch_to_tsquery('english'::regconfig, $1) AS q
WHERE e.search_tsv @@ q
ORDER BY e.id <=| $3
LIMIT 50
"""


def dsn() -> str:
    url = os.environ["DATABASE_URL"]
    return url.replace("postgresql+asyncpg://", "postgresql://").replace("+asyncpg", "")


async def cleanup(conn: asyncpg.Connection) -> None:
    # Delete the user first (cascades subscriptions + entry_states); only then is the
    # feed unreferenced and safe to drop (which cascades its entries).
    await conn.execute("DELETE FROM users WHERE email = $1", BENCH_EMAIL)
    await conn.execute("DELETE FROM feeds WHERE feed_url = $1", BENCH_FEED_URL)


def make_rows(feed_id: int, n: int) -> list[tuple]:
    rng = random.Random(1234)
    rows = []
    for i in range(n):
        words = rng.sample(VOCAB, WORDS_PER_DOC)
        title = " ".join(words[:6])
        body = f"<p>{' '.join(words)}</p>"
        rows.append((feed_id, i.to_bytes(8, "big"), title, body))
    return rows


async def seed(conn: asyncpg.Connection) -> tuple[int, int]:
    await cleanup(conn)
    user_id = await conn.fetchval(
        "INSERT INTO users (email) VALUES ($1) RETURNING id", BENCH_EMAIL
    )
    feed_id = await conn.fetchval(
        "INSERT INTO feeds (feed_url, title) VALUES ($1, $2) RETURNING id",
        BENCH_FEED_URL,
        "Bench Feed",
    )
    await conn.execute(
        "INSERT INTO subscriptions (user_id, feed_id, since_entry_id) VALUES ($1, $2, 0)",
        user_id,
        feed_id,
    )
    print(f"seeding {N:,} entries…", flush=True)
    t0 = time.perf_counter()
    # COPY the base columns; search_tsv (generated STORED) computes per row.
    await conn.copy_records_to_table(
        "entries",
        columns=["feed_id", "guid_hash", "title", "content_html"],
        records=make_rows(feed_id, N),
    )
    await conn.execute("ANALYZE entries")
    print(f"  seeded in {time.perf_counter() - t0:.1f}s", flush=True)
    return user_id, feed_id


async def measure(conn: asyncpg.Connection, user_id: int) -> list[float]:
    rng = random.Random(42)
    stmt = await conn.prepare(SEARCH_SQL)
    anchor = await conn.fetchval("SELECT max(id) FROM entries")  # rum ordering anchor
    latencies_ms: list[float] = []
    for _ in range(ITERATIONS):
        # Mix of single-word and two-word (AND) queries — realistic selectivity.
        term = rng.choice(VOCAB)
        if rng.random() < 0.3:
            term = f"{term} {rng.choice(VOCAB)}"
        t0 = time.perf_counter()
        await stmt.fetch(term, user_id, anchor)
        latencies_ms.append((time.perf_counter() - t0) * 1000)
    return latencies_ms


async def main() -> int:
    conn = await asyncpg.connect(dsn())
    try:
        user_id, _ = await seed(conn)
        # Warm caches, then measure.
        await measure(conn, user_id)
        lat = sorted(await measure(conn, user_id))
        p50 = statistics.median(lat)
        p95 = lat[int(len(lat) * 0.95)]
        p99 = lat[int(len(lat) * 0.99)]
        print(
            f"\nprofile={PROFILE} entries={N:,} iterations={ITERATIONS}\n"
            f"  p50={p50:.1f}ms  p95={p95:.1f}ms  p99={p99:.1f}ms  max={lat[-1]:.1f}ms\n"
            f"  budget: p95 < {P95_BUDGET_MS:.0f}ms",
            flush=True,
        )
        if p95 >= P95_BUDGET_MS:
            print(f"\nFAIL: p95 {p95:.1f}ms exceeds budget {P95_BUDGET_MS:.0f}ms", file=sys.stderr)
            return 1
        print("\nPASS", flush=True)
        return 0
    finally:
        if os.getenv("BENCH_KEEP") != "1":
            await cleanup(conn)
        await conn.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
