"""Test data factories built on the store layer (no direct ORM construction)."""

import hashlib
import itertools

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entry, Feed, Subscription, User
from app.store import entries as entries_store
from app.store import feeds as feeds_store
from app.store import subscriptions as subs_store
from app.store import users as users_store

_seq = itertools.count(1)


async def make_user(session: AsyncSession, **kwargs: object) -> User:
    kwargs.setdefault("email", f"user{next(_seq)}@example.com")
    return await users_store.create(session, **kwargs)  # type: ignore[arg-type]


async def make_feed(session: AsyncSession, *, feed_url: str | None = None, title: str = "") -> Feed:
    feed_url = feed_url or f"http://example.com/feed/{next(_seq)}.xml"
    return await feeds_store.create(session, feed_url=feed_url, title=title)


async def make_subscription(
    session: AsyncSession,
    user: User,
    feed: Feed,
    *,
    folder_id: int | None = None,
    since_entry_id: int = 0,
) -> Subscription:
    return await subs_store.create(
        session,
        user.id,
        feed_id=feed.id,
        folder_id=folder_id,
        since_entry_id=since_entry_id,
    )


async def add_entries(
    session: AsyncSession, feed: Feed, count: int, *, title: str = "entry"
) -> list[Entry]:
    rows: list[entries_store.NewEntry] = []
    for i in range(count):
        guid = hashlib.sha256(f"{feed.id}-{next(_seq)}".encode()).digest()
        rows.append(
            {
                "guid_hash": guid,
                "title": f"{title} {i}",
                "content_html": "<p>body</p>",
            }
        )
    inserted = await entries_store.insert_batch(session, feed.id, rows)
    return sorted(inserted, key=lambda e: e.id)
