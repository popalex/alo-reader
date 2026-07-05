"""Store functions for ``entries`` and stream listing.

``insert_batch`` writes global feed content (not user-scoped). ``list_by_stream`` is
user-scoped (``user_id`` required) and enforces the DESIGN.md §4 read/ordering rules:
newest-first by ``id``, exclusive cursor, unread honoring ``since_entry_id`` and the
per-user ``entry_states`` read flag.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict

from sqlalchemy import Select, and_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Entry, EntryState, Feed, Subscription
from app.store import rowcount
from app.store.stream import Stream, parse_stream


@dataclass(frozen=True)
class StreamRow:
    """An entry plus the joined feed title and this user's read/starred flags."""

    entry: Entry
    feed_title: str
    is_read: bool
    is_starred: bool


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


async def max_id_for_feed(session: AsyncSession, feed_id: int) -> int:
    """Highest entry id currently stored for a feed (0 if none). Used to set a new
    subscription's ``since_entry_id`` so its archive isn't dumped as unread."""
    result = await session.scalar(select(func.max(Entry.id)).where(Entry.feed_id == feed_id))
    return result or 0


def _apply_stream[S: Select[Any]](stmt: S, user_id: int, parsed: Stream, status: str, es: Any) -> S:
    """Add the stream's membership joins + filters to a select that is ``FROM entries``.

    ``es`` is an aliased ``EntryState`` for this user. ``status='unread'`` applies the
    DESIGN.md §4 unread rule (``id > since_entry_id`` and no read flag)."""
    if parsed.kind == "starred":
        # Starred entries for this user (independent of subscription state).
        stmt = stmt.join(
            es,
            and_(es.entry_id == Entry.id, es.user_id == user_id, es.is_starred.is_(True)),
        )
        if status == "unread":
            stmt = stmt.where(or_(es.is_read.is_(None), es.is_read.is_(False)))
    else:
        # all / feed / folder: entries in the user's subscribed feeds.
        stmt = stmt.join(
            Subscription,
            and_(Subscription.feed_id == Entry.feed_id, Subscription.user_id == user_id),
        ).outerjoin(es, and_(es.entry_id == Entry.id, es.user_id == user_id))
        if parsed.kind == "feed":
            stmt = stmt.where(Entry.feed_id == parsed.ref_id)
        elif parsed.kind == "folder":
            stmt = stmt.where(Subscription.folder_id == parsed.ref_id)
        if status == "unread":
            stmt = stmt.where(
                Entry.id > Subscription.since_entry_id,
                or_(es.is_read.is_(None), es.is_read.is_(False)),
            )
    return stmt


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
    stmt = _apply_stream(select(Entry), user_id, parsed, status, es)
    if cursor is not None:
        stmt = stmt.where(Entry.id < cursor)
    stmt = stmt.order_by(Entry.id.desc()).limit(limit)
    result = await session.scalars(stmt)
    return list(result.all())


async def list_stream_page(
    session: AsyncSession,
    user_id: int,
    stream: str | Stream,
    *,
    status: str = "unread",
    cursor: int | None = None,
    limit: int = 50,
) -> list[StreamRow]:
    """Like :func:`list_by_stream` but returns the feed title and per-user read/starred
    flags each entry needs for the HTTP response (DESIGN.md §5)."""
    parsed = stream if isinstance(stream, Stream) else parse_stream(stream)
    es = aliased(EntryState)
    stmt = _apply_stream(
        select(
            Entry,
            Feed.title.label("feed_title"),
            func.coalesce(es.is_read, False).label("is_read"),
            func.coalesce(es.is_starred, False).label("is_starred"),
        ),
        user_id,
        parsed,
        status,
        es,
    ).join(Feed, Feed.id == Entry.feed_id)
    if cursor is not None:
        stmt = stmt.where(Entry.id < cursor)
    stmt = stmt.order_by(Entry.id.desc()).limit(limit)
    rows = await session.execute(stmt)
    return [
        StreamRow(entry=r[0], feed_title=r.feed_title, is_read=r.is_read, is_starred=r.is_starred)
        for r in rows
    ]


async def get_for_user(session: AsyncSession, user_id: int, entry_id: int) -> StreamRow | None:
    """Fetch one entry the user can see (in a subscribed feed), with its metadata.
    Returns None for a missing entry or one in a feed the user isn't subscribed to —
    so another tenant's entry id is indistinguishable from a missing one."""
    es = aliased(EntryState)
    stmt = (
        select(
            Entry,
            Feed.title.label("feed_title"),
            func.coalesce(es.is_read, False).label("is_read"),
            func.coalesce(es.is_starred, False).label("is_starred"),
        )
        .join(
            Subscription,
            and_(Subscription.feed_id == Entry.feed_id, Subscription.user_id == user_id),
        )
        .join(Feed, Feed.id == Entry.feed_id)
        .outerjoin(es, and_(es.entry_id == Entry.id, es.user_id == user_id))
        .where(Entry.id == entry_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return StreamRow(
        entry=row[0], feed_title=row.feed_title, is_read=row.is_read, is_starred=row.is_starred
    )


async def mark_read_bounded(
    session: AsyncSession, user_id: int, stream: str | Stream, max_entry_id: int
) -> int:
    """Mark every entry in ``stream`` with ``id <= max_entry_id`` read for this user.
    Bounded so items arriving mid-action stay unread (DESIGN.md §4). Returns the number
    of entries newly flipped from unread to read."""
    parsed = stream if isinstance(stream, Stream) else parse_stream(stream)
    es = aliased(EntryState)
    src = _apply_stream(
        select(
            literal(user_id).label("user_id"),
            Entry.id.label("entry_id"),
            literal(True).label("is_read"),
            literal(False).label("is_starred"),
            func.now().label("changed_at"),
        ),
        user_id,
        parsed,
        status="all",
        es=es,
    ).where(Entry.id <= max_entry_id)
    stmt = pg_insert(EntryState).from_select(
        ["user_id", "entry_id", "is_read", "is_starred", "changed_at"], src
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "entry_id"],
        set_={"is_read": True, "changed_at": func.now()},
        where=EntryState.is_read.is_(False),  # only count/flip currently-unread rows
    )
    result = await session.execute(stmt)
    return rowcount(result)
