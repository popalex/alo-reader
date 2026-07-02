"""Store functions for the global (deduped) ``feeds`` table.

Feeds are global — one row per unique URL regardless of subscriber count — so these
functions are not user-scoped.
"""

from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Feed


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
