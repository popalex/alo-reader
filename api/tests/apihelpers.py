"""Seeding helpers for the streams/entries/state/counts API tests (not collected)."""

import itertools

from app import db as app_db
from app.store import entries as entries_store
from app.store import feeds as feeds_store
from app.store import subscriptions as subs_store
from app.store.entries import NewEntry

_seq = itertools.count(1)


async def seed_feed_with_entries(
    user_id: int,
    n: int,
    *,
    since_entry_id: int = 0,
    folder_id: int | None = None,
    feed_url: str | None = None,
) -> tuple[int, list[int]]:
    """Create a feed with ``n`` entries and subscribe ``user_id`` to it. Returns
    ``(feed_id, entry_ids)`` with entry ids sorted ascending (insertion order)."""
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        feed = await feeds_store.create(
            s, feed_url=feed_url or f"https://f{next(_seq)}.example/rss", title="Feed"
        )
        rows: list[NewEntry] = [
            {
                "guid_hash": i.to_bytes(8, "big"),
                "title": f"entry {i}",
                "content_html": f"<p>Body number {i} with several words.</p>",
            }
            for i in range(n)
        ]
        inserted = await entries_store.insert_batch(s, feed.id, rows)
        await subs_store.create(
            s, user_id, feed_id=feed.id, since_entry_id=since_entry_id, folder_id=folder_id
        )
        return feed.id, sorted(e.id for e in inserted)


async def add_entries(feed_id: int, n: int, *, start: int) -> list[int]:
    """Append ``n`` more entries to an existing feed. ``start`` offsets guid_hash so
    they don't collide with earlier ones."""
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        rows: list[NewEntry] = [
            {
                "guid_hash": (start + i).to_bytes(8, "big"),
                "title": f"entry {start + i}",
                "content_html": f"<p>Body {start + i}.</p>",
            }
            for i in range(n)
        ]
        inserted = await entries_store.insert_batch(s, feed_id, rows)
        return sorted(e.id for e in inserted)
