"""Stream listing: ordering, cursor pagination, since_entry_id, starred."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.store import entries as entries_store
from app.store import entry_states as states_store
from tests.factories import add_entries, make_feed, make_subscription, make_user


async def test_since_entry_id_hides_pre_subscription(session: AsyncSession) -> None:
    user = await make_user(session)
    feed = await make_feed(session)
    ents = await add_entries(session, feed, 5)
    # Subscribe as of the 3rd entry: only entries strictly after it are unread.
    await make_subscription(session, user, feed, since_entry_id=ents[2].id)

    unread = await entries_store.list_by_stream(session, user.id, "all", status="unread")
    assert [e.id for e in unread] == [ents[4].id, ents[3].id]

    # status=all ignores the unread cutoff.
    all_ = await entries_store.list_by_stream(session, user.id, "all", status="all")
    assert len(all_) == 5


async def test_cursor_pagination_gap_free_during_inserts(session: AsyncSession) -> None:
    user = await make_user(session)
    feed = await make_feed(session)
    await make_subscription(session, user, feed)
    first = await add_entries(session, feed, 6)

    page1 = await entries_store.list_by_stream(session, user.id, "all", status="all", limit=3)
    assert [e.id for e in page1] == [e.id for e in reversed(first[3:])]

    # New entries arrive mid-pagination; the exclusive cursor keeps page 2 stable.
    await add_entries(session, feed, 4)
    page2 = await entries_store.list_by_stream(
        session, user.id, "all", status="all", cursor=page1[-1].id, limit=3
    )
    assert [e.id for e in page2] == [e.id for e in reversed(first[:3])]

    ids = [e.id for e in page1] + [e.id for e in page2]
    assert len(ids) == len(set(ids))  # no duplicates
    assert ids == sorted(ids, reverse=True)  # strictly newest-first


async def test_starred_stream(session: AsyncSession) -> None:
    user = await make_user(session)
    feed = await make_feed(session)
    await make_subscription(session, user, feed)
    ents = await add_entries(session, feed, 3)
    now = datetime.now(UTC)
    await states_store.upsert(session, user.id, ents[1].id, changed_at=now, is_starred=True)

    starred = await entries_store.list_by_stream(session, user.id, "starred", status="all")
    assert [e.id for e in starred] == [ents[1].id]


async def test_feed_stream_is_tenant_scoped(session: AsyncSession) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    feed = await make_feed(session)
    await make_subscription(session, alice, feed)
    await add_entries(session, feed, 3)

    # Bob is not subscribed → sees nothing for that feed.
    bob_view = await entries_store.list_by_stream(session, bob.id, f"feed/{feed.id}", status="all")
    assert bob_view == []
