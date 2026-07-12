"""Stream listing: ordering, cursor pagination, since_entry_id, starred."""

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entry
from app.store import entries as entries_store
from app.store import entry_states as states_store
from tests.factories import add_entries, make_feed, make_subscription, make_user


async def _set_published(session: AsyncSession, entry_id: int, iso: str) -> None:
    await session.execute(
        update(Entry).where(Entry.id == entry_id).values(published_at=datetime.fromisoformat(iso))
    )


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

    # New entries arrive mid-pagination; the keyset cursor keeps page 2 stable.
    await add_entries(session, feed, 4)
    cursor = entries_store.encode_cursor(page1[-1].published_at, page1[-1].created_at, page1[-1].id)
    page2 = await entries_store.list_by_stream(
        session, user.id, "all", status="all", cursor=cursor, limit=3
    )
    assert [e.id for e in page2] == [e.id for e in reversed(first[:3])]

    ids = [e.id for e in page1] + [e.id for e in page2]
    assert len(ids) == len(set(ids))  # no duplicates
    assert ids == sorted(ids, reverse=True)  # strictly newest-first


async def test_listing_orders_by_publish_date_not_id(session: AsyncSession) -> None:
    # Operator ordering: the feed's own publish date drives the list, even when it
    # runs opposite to insertion/id order (a backfill loaded newest-first).
    user = await make_user(session)
    feed = await make_feed(session)
    await make_subscription(session, user, feed)
    e = await add_entries(session, feed, 3)  # ids ascending: e[0] < e[1] < e[2]
    await _set_published(session, e[0].id, "2024-01-01T00:00:00+00:00")  # newest
    await _set_published(session, e[1].id, "2022-01-01T00:00:00+00:00")  # oldest
    await _set_published(session, e[2].id, "2023-01-01T00:00:00+00:00")  # middle

    rows = await entries_store.list_by_stream(session, user.id, "all", status="all")
    assert [r.id for r in rows] == [e[0].id, e[2].id, e[1].id]  # 2024, 2023, 2022


async def test_recency_cursor_paginates_gap_free(session: AsyncSession) -> None:
    user = await make_user(session)
    feed = await make_feed(session)
    await make_subscription(session, user, feed)
    e = await add_entries(session, feed, 5)
    # Publish dates scrambled vs id order.
    for entry, iso in zip(
        e,
        [
            "2020-01-01T00:00:00+00:00",
            "2024-01-01T00:00:00+00:00",
            "2021-01-01T00:00:00+00:00",
            "2023-01-01T00:00:00+00:00",
            "2022-01-01T00:00:00+00:00",
        ],
        strict=True,
    ):
        await _set_published(session, entry.id, iso)

    full = await entries_store.list_by_stream(session, user.id, "all", status="all")
    expected = [r.id for r in full]  # by publish date desc

    # Walk it in pages of 2 via the composite cursor; must reproduce the full order.
    seen: list[int] = []
    cursor: str | None = None
    for _ in range(10):
        page = await entries_store.list_by_stream(
            session, user.id, "all", status="all", cursor=cursor, limit=2
        )
        if not page:
            break
        seen += [r.id for r in page]
        last = page[-1]
        cursor = entries_store.encode_cursor(last.published_at, last.created_at, last.id)
    assert seen == expected
    assert len(seen) == len(set(seen))  # gap-free, dup-free


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
