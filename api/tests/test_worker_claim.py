"""Claim-loop concurrency + lease recovery (DESIGN.md §1.3).

Two workers draining a shared backlog must never double-insert (FOR UPDATE SKIP
LOCKED + the (feed_id, guid_hash) unique index), and an expired lease from a
crashed worker must become claimable again.
"""

import asyncio

import httpx
import pytest
from sqlalchemy import text, update

from app import db as app_db
from app.models import Feed
from app.worker.main import poll_once
from tests import wutil

pytestmark = pytest.mark.usefixtures("public_dns")

_ITEMS = [("g1", "One"), ("g2", "Two"), ("g3", "Three")]


async def test_two_workers_no_duplicate_entries(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    feed_ids = [await wutil.seed_feed(sf, f"https://feed{i}.example/rss") for i in range(50)]
    # One rude origin body reused by every feed; small batches force real contention.
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=wutil.rss(_ITEMS)))
    settings = wutil.worker_settings(worker_claim_batch=5, worker_max_concurrency=10)

    async def worker() -> None:
        while await poll_once(sf, settings=settings, transport=transport) > 0:
            await asyncio.sleep(0)  # cede so both workers actually interleave

    await asyncio.gather(worker(), worker())

    # Every feed got exactly its 3 items, once — 150 rows total, no duplicates.
    per_feed = [await wutil.count_entries(sf, fid) for fid in feed_ids]
    assert per_feed == [3] * 50
    async with sf() as s:
        total = (await s.scalars(text("SELECT count(*) FROM entries"))).one()
    assert total == 150


async def test_expired_lease_is_reclaimed(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    feed_id = await wutil.seed_feed(sf, "https://feed.example/rss")
    transport = wutil.serve(wutil.rss(_ITEMS))
    settings = wutil.worker_settings()

    # Simulate a crashed worker still holding a live lease: due, but claimed.
    async with sf() as s, s.begin():
        await s.execute(
            update(Feed)
            .where(Feed.id == feed_id)
            .values(claimed_until=text("now() + interval '2 minutes'"))
        )
    assert await poll_once(sf, settings=settings, transport=transport) == 0
    assert await wutil.count_entries(sf, feed_id) == 0

    # Lease expires → the feed is claimable again and gets processed.
    async with sf() as s, s.begin():
        await s.execute(
            update(Feed)
            .where(Feed.id == feed_id)
            .values(claimed_until=text("now() - interval '1 second'"))
        )
    assert await poll_once(sf, settings=settings, transport=transport) == 1
    assert await wutil.count_entries(sf, feed_id) == 3
