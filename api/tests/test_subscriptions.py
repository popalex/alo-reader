"""Unsubscribe cleanup: delete removes all of a feed when nobody's left, but keeps a
shared feed (only dropping the leaving user's read/star state)."""

import asyncio
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import db as app_db
from app.models import Entry, EntryState, Feed
from app.store import entry_states as states_store
from app.store import subscriptions as subs_store
from tests.factories import add_entries, make_feed, make_subscription, make_user


async def _count(session: AsyncSession, model: type, **filters: object) -> int:
    stmt = select(func.count()).select_from(model)
    for col, val in filters.items():
        stmt = stmt.where(getattr(model, col) == val)
    return await session.scalar(stmt) or 0


async def test_delete_removes_orphaned_feed_and_all_state(session: AsyncSession) -> None:
    user = await make_user(session)
    feed = await make_feed(session)
    sub = await make_subscription(session, user, feed)
    ents = await add_entries(session, feed, 3)
    now = datetime.now(UTC)
    await states_store.upsert(session, user.id, ents[0].id, changed_at=now, is_read=True)

    assert await subs_store.delete(session, user.id, sub.id) is True

    # Nobody left subscribed → the feed, its entries, and all read/star state are gone.
    assert await session.get(Feed, feed.id) is None
    assert await _count(session, Entry, feed_id=feed.id) == 0
    assert await _count(session, EntryState, user_id=user.id) == 0


async def test_delete_keeps_feed_with_other_subscribers(session: AsyncSession) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    feed = await make_feed(session)
    a_sub = await make_subscription(session, alice, feed)
    await make_subscription(session, bob, feed)
    ents = await add_entries(session, feed, 2)
    now = datetime.now(UTC)
    await states_store.upsert(session, alice.id, ents[0].id, changed_at=now, is_read=True)
    await states_store.upsert(session, bob.id, ents[0].id, changed_at=now, is_read=True)

    assert await subs_store.delete(session, alice.id, a_sub.id) is True

    # Bob is still subscribed → feed + entries stay; only Alice's state is removed.
    assert await session.get(Feed, feed.id) is not None
    assert await _count(session, Entry, feed_id=feed.id) == 2
    assert await _count(session, EntryState, user_id=alice.id) == 0
    assert await _count(session, EntryState, user_id=bob.id) == 1


async def test_unsubscribe_survives_a_concurrent_subscribe(api_db: str) -> None:
    # The last subscriber leaving counts remaining = 0 without seeing an uncommitted
    # concurrent subscribe, so the feed DELETE can hit a foreign key violation once
    # that transaction commits. Unscoped, that error takes the whole unsubscribe with
    # it: a 500, with the subscription row already gone.
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        alice = await make_user(s, clerk_user_id="race_alice")
        bob = await make_user(s, clerk_user_id="race_bob")
        feed = await make_feed(s)
        sub = await subs_store.create(s, alice.id, feed_id=feed.id)
        alice_id, bob_id, feed_id, sub_id = alice.id, bob.id, feed.id, sub.id

    # Bob subscribes in a transaction that is still open when Alice unsubscribes.
    bob_session = sf()
    await bob_session.begin()
    await subs_store.create(bob_session, bob_id, feed_id=feed_id)

    async def unsubscribe() -> bool:
        async with sf() as s, s.begin():
            return await subs_store.delete(s, alice_id, sub_id)

    task = asyncio.create_task(unsubscribe())
    await asyncio.sleep(0.2)  # let it reach the blocking DELETE
    await bob_session.commit()
    await bob_session.close()

    assert await task is True
    async with sf() as s:
        assert await s.get(Feed, feed_id) is not None  # Bob's subscription kept it
        assert await subs_store.count_for_user(s, bob_id) == 1
        assert await subs_store.count_for_user(s, alice_id) == 0
