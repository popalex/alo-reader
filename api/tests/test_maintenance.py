"""Worker-embedded maintenance (WP-15): orphan-feed GC + retention purge.

Real Postgres (api_db): exercises the trigger-maintained ``orphaned_at``, the GC
grace period + entry cascade, and every branch of the DESIGN.md §0.3/§4 retention
rule. Rows are aged with direct UPDATEs to stand in for elapsed time.
"""

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import db as app_db
from app.config import Settings
from app.models import Entry, EntryState, Feed
from app.store import entries as entries_store
from app.store import feeds as feeds_store
from app.worker.maintenance import next_wait, run_maintenance
from tests import factories


async def _age_orphan(sf: async_sessionmaker[AsyncSession], feed_id: int, days: float) -> None:
    async with sf() as s, s.begin():
        await s.execute(
            text("UPDATE feeds SET orphaned_at = now() - (:d * interval '1 day') WHERE id = :id"),
            {"d": days, "id": feed_id},
        )


async def _age_entry(sf: async_sessionmaker[AsyncSession], entry_id: int, days: float) -> None:
    async with sf() as s, s.begin():
        await s.execute(
            text("UPDATE entries SET created_at = now() - (:d * interval '1 day') WHERE id = :id"),
            {"d": days, "id": entry_id},
        )


async def _orphaned_at(sf: async_sessionmaker[AsyncSession], feed_id: int) -> datetime | None:
    async with sf() as s:
        return await s.scalar(select(Feed.orphaned_at).where(Feed.id == feed_id))


async def _set_state(
    sf: async_sessionmaker[AsyncSession],
    user_id: int,
    entry_id: int,
    *,
    read: bool = False,
    starred: bool = False,
) -> None:
    async with sf() as s, s.begin():
        s.add(
            EntryState(
                user_id=user_id,
                entry_id=entry_id,
                is_read=read,
                is_starred=starred,
                changed_at=datetime.now(UTC),
            )
        )


# ── Orphan trigger ───────────────────────────────────────────────────────────


async def test_orphan_trigger_sets_and_clears(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        user = await factories.make_user(s)
        feed = await factories.make_feed(s)
        feed_id, user_id = feed.id, user.id
    # A bare feed with no subscribers starts orphaned (default now()).
    assert await _orphaned_at(sf, feed_id) is not None

    async with sf() as s, s.begin():
        sub = await factories.make_subscription(s, user, feed)
        sub_id = sub.id
    assert await _orphaned_at(sf, feed_id) is None  # subscribing clears it

    # A second subscriber, then remove the first: still has a subscriber → not orphaned.
    async with sf() as s, s.begin():
        other = await factories.make_user(s)
        await factories.make_subscription(s, other, feed)
    async with sf() as s, s.begin():
        await s.execute(text("DELETE FROM subscriptions WHERE id = :id"), {"id": sub_id})
    assert await _orphaned_at(sf, feed_id) is None

    # Remove the last remaining subscriber → orphaned again.
    async with sf() as s, s.begin():
        await s.execute(text("DELETE FROM subscriptions WHERE feed_id = :id"), {"id": feed_id})
    assert await _orphaned_at(sf, feed_id) is not None
    _ = (user_id, sub_id)


async def test_orphan_gc_respects_grace_and_subscribers(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        user = await factories.make_user(s)
        long_orphan = await factories.make_feed(s, feed_url="https://a.example/rss")
        recent_orphan = await factories.make_feed(s, feed_url="https://b.example/rss")
        subscribed = await factories.make_feed(s, feed_url="https://c.example/rss")
        await factories.make_subscription(s, user, subscribed)
        ids = (long_orphan.id, recent_orphan.id, subscribed.id)

    await _age_orphan(sf, ids[0], 8)  # past the 7-day grace
    await _age_orphan(sf, ids[1], 3)  # inside the grace

    async with sf() as s, s.begin():
        deleted = await feeds_store.delete_orphaned(s, grace=timedelta(days=7))
    assert deleted == 1

    async with sf() as s:
        remaining = set((await s.scalars(select(Feed.id))).all())
    assert ids[0] not in remaining  # long-orphaned → gone
    assert ids[1] in remaining  # inside grace → kept
    assert ids[2] in remaining  # has a subscriber → kept


async def test_orphan_gc_cascades_entries(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        feed = await factories.make_feed(s)
        await factories.add_entries(s, feed, 5)
        feed_id = feed.id
    await _age_orphan(sf, feed_id, 30)

    async with sf() as s, s.begin():
        assert await feeds_store.delete_orphaned(s, grace=timedelta(days=7)) == 1
    async with sf() as s:
        left = await s.scalar(
            select(func.count()).select_from(Entry).where(Entry.feed_id == feed_id)
        )
    assert left == 0  # entries cascaded with the feed


# ── Retention purge ──────────────────────────────────────────────────────────


async def _purge(sf: async_sessionmaker[AsyncSession], days: int = 90) -> int:
    async with sf() as s, s.begin():
        return await entries_store.purge_retained(s, horizon=timedelta(days=days))


async def _surviving_ids(sf: async_sessionmaker[AsyncSession], feed_id: int) -> set[int]:
    async with sf() as s:
        return set((await s.scalars(select(Entry.id).where(Entry.feed_id == feed_id))).all())


async def test_retention_purge_rules(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        user = await factories.make_user(s)
        feed = await factories.make_feed(s)
        await factories.make_subscription(s, user, feed)
        entries = await factories.add_entries(s, feed, 5)
        user_id, feed_id = user.id, feed.id
    old_read, old_unread, old_starred, recent_read, old_read_2 = [e.id for e in entries]

    # Age everything except the "recent" one well past the horizon.
    for eid in (old_read, old_unread, old_starred, old_read_2):
        await _age_entry(sf, eid, 100)
    await _age_entry(sf, recent_read, 1)

    await _set_state(sf, user_id, old_read, read=True)
    await _set_state(sf, user_id, old_starred, read=True, starred=True)  # starred wins
    await _set_state(sf, user_id, recent_read, read=True)
    await _set_state(sf, user_id, old_read_2, read=True)
    # old_unread: no state → unread for the subscriber.

    purged = await _purge(sf)
    survivors = await _surviving_ids(sf, feed_id)

    assert old_read not in survivors  # old + read by every subscriber → purged
    assert old_read_2 not in survivors
    assert old_unread in survivors  # unread is never purged
    assert old_starred in survivors  # starred kept forever
    assert recent_read in survivors  # inside the horizon
    assert purged == 2


async def test_purge_keeps_entry_unread_by_another_subscriber(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        reader = await factories.make_user(s)
        laggard = await factories.make_user(s)
        feed = await factories.make_feed(s)
        await factories.make_subscription(s, reader, feed)
        await factories.make_subscription(s, laggard, feed)
        entries = await factories.add_entries(s, feed, 1)
        reader_id, feed_id, eid = reader.id, feed.id, entries[0].id
    await _age_entry(sf, eid, 100)
    await _set_state(sf, reader_id, eid, read=True)  # laggard has not read it

    await _purge(sf)
    assert eid in await _surviving_ids(sf, feed_id)  # one subscriber still hasn't read → kept


async def test_purge_treats_pre_subscription_entries_as_read(api_db: str) -> None:
    # An entry with id <= since_entry_id predates the subscription: it was never
    # "unread" for that subscriber, so it doesn't block the purge.
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        user = await factories.make_user(s)
        feed = await factories.make_feed(s)
        entries = await factories.add_entries(s, feed, 1)
        eid = entries[0].id
        # Subscribe with a since_entry_id at/above the entry → it predates the sub.
        await factories.make_subscription(s, user, feed, since_entry_id=eid)
        feed_id = feed.id
    await _age_entry(sf, eid, 100)

    await _purge(sf)
    assert eid not in await _surviving_ids(sf, feed_id)  # predates sub → purgeable


# ── Sweep + jitter ───────────────────────────────────────────────────────────


async def test_run_maintenance_sweeps_both(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        user = await factories.make_user(s)
        orphan = await factories.make_feed(s, feed_url="https://gone.example/rss")
        live = await factories.make_feed(s, feed_url="https://live.example/rss")
        await factories.make_subscription(s, user, live)
        entries = await factories.add_entries(s, live, 1)
        orphan_id, purge_id = orphan.id, entries[0].id
    await _age_orphan(sf, orphan_id, 30)
    await _age_entry(sf, purge_id, 100)
    await _set_state(sf, user.id, purge_id, read=True)

    settings = Settings(database_url="postgresql+asyncpg://x/y", auth_mode="none")  # type: ignore[call-arg]
    gc, purged = await run_maintenance(sf, settings=settings)
    assert gc == 1 and purged == 1


def test_next_wait_within_jitter_bounds() -> None:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://x/y",
        auth_mode="none",
        worker_maintenance_interval_s=1000.0,
        worker_maintenance_jitter_s=100.0,
    )
    rng = random.Random(0)
    for _ in range(200):
        w = next_wait(settings, rng)
        assert 900.0 <= w <= 1100.0


def test_next_wait_clamped_non_negative() -> None:
    settings = Settings(  # type: ignore[call-arg]
        database_url="postgresql+asyncpg://x/y",
        auth_mode="none",
        worker_maintenance_interval_s=10.0,
        worker_maintenance_jitter_s=100.0,  # jitter can exceed the interval
    )
    rng = random.Random(1)
    assert all(next_wait(settings, rng) >= 0.0 for _ in range(200))
