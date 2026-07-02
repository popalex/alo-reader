"""Store functions for ``entries`` and stream listing.

``insert_batch`` writes global feed content (not user-scoped). ``list_by_stream`` is
user-scoped (``user_id`` required) and enforces the DESIGN.md §4 read/ordering rules:
newest-first by ``id``, exclusive cursor, unread honoring ``since_entry_id`` and the
per-user ``entry_states`` read flag.
"""

from datetime import datetime
from typing import Any, TypedDict

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Entry, EntryState, Subscription
from app.store.stream import Stream, parse_stream


class NewEntry(TypedDict, total=False):
    guid_hash: bytes
    url: str | None
    title: str
    author: str | None
    content_html: str
    content_raw: bytes | None
    published_at: datetime | None


async def insert_batch(session: AsyncSession, feed_id: int, entries: list[NewEntry]) -> list[Entry]:
    """Insert new entries for a feed, skipping duplicates on ``(feed_id, guid_hash)``.
    Returns only the rows actually inserted."""
    if not entries:
        return []
    rows: list[dict[str, Any]] = [{"feed_id": feed_id, **e} for e in entries]
    stmt = (
        pg_insert(Entry)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["feed_id", "guid_hash"])
        .returning(Entry)
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def get(session: AsyncSession, entry_id: int) -> Entry | None:
    return await session.get(Entry, entry_id)


async def list_by_stream(
    session: AsyncSession,
    user_id: int,
    stream: str | Stream,
    *,
    status: str = "unread",
    cursor: int | None = None,
    limit: int = 50,
) -> list[Entry]:
    parsed = stream if isinstance(stream, Stream) else parse_stream(stream)
    es = aliased(EntryState)

    if parsed.kind == "starred":
        # Starred entries for this user (independent of subscription state).
        stmt = select(Entry).join(
            es,
            and_(
                es.entry_id == Entry.id,
                es.user_id == user_id,
                es.is_starred.is_(True),
            ),
        )
        if status == "unread":
            stmt = stmt.where(or_(es.is_read.is_(None), es.is_read.is_(False)))
    else:
        # all / feed / folder: entries in the user's subscribed feeds.
        stmt = (
            select(Entry)
            .join(
                Subscription,
                and_(
                    Subscription.feed_id == Entry.feed_id,
                    Subscription.user_id == user_id,
                ),
            )
            .outerjoin(
                es,
                and_(es.entry_id == Entry.id, es.user_id == user_id),
            )
        )
        if parsed.kind == "feed":
            stmt = stmt.where(Entry.feed_id == parsed.ref_id)
        elif parsed.kind == "folder":
            stmt = stmt.where(Subscription.folder_id == parsed.ref_id)
        if status == "unread":
            stmt = stmt.where(
                Entry.id > Subscription.since_entry_id,
                or_(es.is_read.is_(None), es.is_read.is_(False)),
            )

    if cursor is not None:
        stmt = stmt.where(Entry.id < cursor)
    stmt = stmt.order_by(Entry.id.desc()).limit(limit)

    result = await session.scalars(stmt)
    return list(result.all())
