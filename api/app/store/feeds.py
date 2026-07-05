"""Store functions for the global (deduped) ``feeds`` table.

Feeds are global — one row per unique URL regardless of subscriber count — so these
functions are not user-scoped.
"""

from datetime import timedelta

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Feed
from app.store import rowcount

# A released lease: 1970, always in the past, so the row is immediately claimable.
_RELEASED = text("'epoch'::timestamptz")
# Cap stored error text so a hostile server message can't bloat the row.
_MAX_ERROR_LEN = 2000


async def create(
    session: AsyncSession,
    *,
    feed_url: str,
    site_url: str | None = None,
    title: str = "",
) -> Feed:
    feed = Feed(feed_url=feed_url, site_url=site_url, title=title)
    session.add(feed)
    await session.flush()
    return feed


async def get(session: AsyncSession, feed_id: int) -> Feed | None:
    return await session.get(Feed, feed_id)


async def get_by_url(session: AsyncSession, feed_url: str) -> Feed | None:
    result = await session.scalars(select(Feed).where(Feed.feed_url == feed_url))
    return result.first()


async def upsert_by_url(
    session: AsyncSession,
    *,
    feed_url: str,
    site_url: str | None = None,
    title: str = "",
) -> Feed:
    """Return the existing feed for ``feed_url`` or create one queued for an
    immediate poll (``next_check_at = now()``)."""
    existing = await get_by_url(session, feed_url)
    if existing is not None:
        return existing
    feed = Feed(feed_url=feed_url, site_url=site_url, title=title, next_check_at=func.now())
    session.add(feed)
    await session.flush()
    return feed


async def request_immediate_check(session: AsyncSession, feed_id: int) -> bool:
    """Queue a feed for the next poll cycle (``next_check_at = now()``). Used by the
    manual /subscriptions/{id}/refresh path. Returns False if the feed is gone."""
    result = await session.execute(
        update(Feed).where(Feed.id == feed_id).values(next_check_at=func.now())
    )
    return rowcount(result) > 0


async def claim_due_feeds(
    session: AsyncSession, *, limit: int = 50, lease_seconds: int = 120
) -> list[Feed]:
    """Claim up to ``limit`` due, unclaimed feeds using ``FOR UPDATE SKIP LOCKED``
    (DESIGN.md §1.3). Sets a ``claimed_until`` lease so N workers can claim disjoint
    batches crash-safely. The worker loop that calls this lands in WP-05.
    """
    due = (
        select(Feed.id)
        .where(Feed.next_check_at <= func.now(), Feed.claimed_until < func.now())
        .order_by(Feed.next_check_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    stmt = (
        update(Feed)
        .where(Feed.id.in_(due))
        .values(claimed_until=func.now() + timedelta(seconds=lease_seconds))
        .returning(Feed)
    )
    result = await session.scalars(stmt)
    return list(result.all())


async def record_success(
    session: AsyncSession,
    feed_id: int,
    *,
    interval_s: int,
    etag: str | None,
    last_modified: str | None,
    title: str,
    site_url: str | None,
) -> None:
    """Persist a successful poll: refresh metadata/validators, schedule the next
    check ``interval_s`` out, clear the error state, and release the lease."""
    await session.execute(
        update(Feed)
        .where(Feed.id == feed_id)
        .values(
            etag=etag,
            last_modified=last_modified,
            title=title,
            site_url=site_url,
            check_interval_s=interval_s,
            next_check_at=func.now() + timedelta(seconds=interval_s),
            error_count=0,
            last_error=None,
            last_fetched_at=func.now(),
            claimed_until=_RELEASED,
        )
    )


async def record_not_modified(session: AsyncSession, feed_id: int, *, interval_s: int) -> None:
    """Persist a ``304``: reschedule and clear errors, leaving content untouched."""
    await session.execute(
        update(Feed)
        .where(Feed.id == feed_id)
        .values(
            check_interval_s=interval_s,
            next_check_at=func.now() + timedelta(seconds=interval_s),
            error_count=0,
            last_error=None,
            last_fetched_at=func.now(),
            claimed_until=_RELEASED,
        )
    )


async def record_error(session: AsyncSession, feed_id: int, *, delay_s: int, message: str) -> None:
    """Persist a failed poll: bump ``error_count``, store ``last_error``, back off
    ``delay_s``, and release the lease. Feeds are never auto-deleted."""
    await session.execute(
        update(Feed)
        .where(Feed.id == feed_id)
        .values(
            error_count=Feed.error_count + 1,
            last_error=message[:_MAX_ERROR_LEN],
            next_check_at=func.now() + timedelta(seconds=delay_s),
            claimed_until=_RELEASED,
        )
    )


async def update_feed_url(session: AsyncSession, feed_id: int, new_url: str) -> bool:
    """Repoint a permanently-redirected feed. Returns ``False`` on a unique
    collision (another feed already lives at ``new_url``) — the caller must mark an
    error rather than silently merge two feeds."""
    try:
        async with session.begin_nested():
            await session.execute(update(Feed).where(Feed.id == feed_id).values(feed_url=new_url))
    except IntegrityError:
        return False
    return True
