"""Store functions for ``entries`` and stream listing.

``insert_batch`` writes global feed content (not user-scoped). ``list_by_stream`` is
user-scoped (``user_id`` required) and enforces the DESIGN.md §4 read/ordering rules:
newest-first by ``id``, exclusive cursor, unread honoring ``since_entry_id`` and the
per-user ``entry_states`` read flag.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, TypedDict

from sqlalchemy import BigInteger, Select, and_, func, literal, literal_column, or_, select, text
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


@dataclass(frozen=True)
class SearchRow(StreamRow):
    """A :class:`StreamRow` plus a highlighted ``ts_headline`` snippet (``<b>`` marks)."""

    snippet: str


class NewEntry(TypedDict, total=False):
    guid_hash: bytes
    url: str | None
    title: str
    author: str | None
    content_html: str
    content_raw: bytes | None
    content_truncated: bool
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


# Retention purge (DESIGN.md §0.3, §4): delete an entry only when it is older than
# the horizon AND starred by no one AND, for every subscriber, either it predates
# that subscription (id <= since_entry_id) or that subscriber has read it. Unread is
# never purged. Global content (not user-scoped). Written as SQL because the "every
# subscriber has read-or-unsubscribed" rule is a NOT EXISTS over the unread set.
_PURGE_SQL = text("""
    DELETE FROM entries e
     WHERE e.created_at < now() - (:horizon_s * interval '1 second')
       AND NOT EXISTS (
             SELECT 1 FROM entry_states st
              WHERE st.entry_id = e.id AND st.is_starred)
       AND NOT EXISTS (
             SELECT 1 FROM subscriptions s
              WHERE s.feed_id = e.feed_id
                AND e.id > s.since_entry_id
                AND NOT EXISTS (
                      SELECT 1 FROM entry_states st2
                       WHERE st2.entry_id = e.id
                         AND st2.user_id = s.user_id
                         AND st2.is_read))
""")


async def purge_retained(session: AsyncSession, *, horizon: timedelta) -> int:
    """Purge entries past the retention horizon per the DESIGN.md §0.3 rule.
    Returns the number of entries deleted."""
    result = await session.execute(_PURGE_SQL, {"horizon_s": horizon.total_seconds()})
    return rowcount(result)


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


# Cap for search pages: ts_headline re-parses each returned document, so it must
# only ever run on a bounded page, never across the whole match set (DESIGN §4.1.5).
SEARCH_LIMIT = 50

# ts_headline options — highlight matches with <b>…</b> (the markers the frontend
# renders), bounded to a short excerpt. The frontend HTML-escapes everything except
# those markers, so the tag choice here is the safe-list.
_HEADLINE_OPTS = (
    "StartSel=<b>, StopSel=</b>, MaxWords=32, MinWords=12, MaxFragments=2, FragmentDelimiter= … "
)

# 'english'::regconfig as a SQL literal (not a bound param): the text/regconfig
# overload of websearch_to_tsquery/ts_headline needs the config typed as regconfig,
# and it's a constant, never user input.
_ENGLISH: Any = literal_column("'english'::regconfig")


async def search_stream_page(
    session: AsyncSession,
    user_id: int,
    stream: str | Stream,
    *,
    q: str,
    status: str = "all",
    cursor: int | None = None,
    limit: int = SEARCH_LIMIT,
) -> list[SearchRow]:
    """Full-text search within a stream (DESIGN.md §4.1).

    Uses ``websearch_to_tsquery('english', q)`` against the ``search_tsv`` generated
    column (Google-like syntax; never raises on malformed input). Results stay strictly
    ``id DESC`` — chronological, never ``ts_rank`` (§4.1.4) — and stream-scoped/tenant-
    isolated exactly like the normal listing. ``ts_headline`` runs only on the returned
    page because ``limit`` is capped (§4.1.5); the caller must not exceed ``SEARCH_LIMIT``.
    """
    parsed = stream if isinstance(stream, Stream) else parse_stream(stream)
    es = aliased(EntryState)
    tsquery = func.websearch_to_tsquery(_ENGLISH, q)
    snippet = func.ts_headline(
        _ENGLISH,
        func.left(func.strip_html(Entry.content_html), 20000),
        tsquery,
        _HEADLINE_OPTS,
    ).label("snippet")
    base = _apply_stream(
        select(
            Entry,
            Feed.title.label("feed_title"),
            func.coalesce(es.is_read, False).label("is_read"),
            func.coalesce(es.is_starred, False).label("is_starred"),
            snippet,
        ),
        user_id,
        parsed,
        status,
        es,
    ).join(Feed, Feed.id == Entry.feed_id)
    if cursor is not None:
        base = base.where(Entry.id < cursor)

    # Feed-name coverage (title/author/content are already in search_tsv; the feed's
    # own name is not). Resolve the few name-matching feeds first: a query that OR's
    # in feed membership is no longer a pure `@@`, so the rum index can't drive the
    # id ordering and we fall back to a sort — acceptable because it only happens
    # when a query matches a *subscribed feed's name* (rare). The common case stays
    # on the rum index.
    feed_ids = (
        await session.scalars(select(Feed.id).where(Feed.search_tsv.op("@@")(tsquery)))
    ).all()

    if feed_ids:
        stmt = base.where(
            or_(Entry.search_tsv.op("@@")(tsquery), Entry.feed_id.in_(feed_ids))
        ).order_by(Entry.id.desc())
    else:
        # rum index-ordered scan: `id <=| anchor` returns matches by descending id
        # straight from the index (no sort). The anchor sits at/above the top id
        # (max id for page 1, the cursor for later pages) so distances stay small and
        # exact in float; the `id < cursor` filter above keeps a short last page from
        # pulling in ids above the cursor (DESIGN.md §4.1).
        anchor = (
            cursor - 1 if cursor is not None else await session.scalar(select(func.max(Entry.id)))
        )
        if anchor is None:
            return []
        stmt = base.where(Entry.search_tsv.op("@@")(tsquery)).order_by(
            Entry.id.op("<=|")(literal(anchor, BigInteger))
        )

    stmt = stmt.limit(min(limit, SEARCH_LIMIT))
    rows = await session.execute(stmt)
    return [
        SearchRow(
            entry=r[0],
            feed_title=r.feed_title,
            is_read=r.is_read,
            is_starred=r.is_starred,
            snippet=r.snippet,
        )
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
