"""Store functions for ``subscriptions`` — all user-scoped (``user_id`` required)."""

from collections.abc import Sequence

from sqlalchemy import Row, func, select
from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entry, EntryState, Feed, Icon, Subscription


async def create(
    session: AsyncSession,
    user_id: int,
    *,
    feed_id: int,
    folder_id: int | None = None,
    title_override: str | None = None,
    since_entry_id: int = 0,
) -> Subscription:
    sub = Subscription(
        user_id=user_id,
        feed_id=feed_id,
        folder_id=folder_id,
        title_override=title_override,
        since_entry_id=since_entry_id,
    )
    session.add(sub)
    await session.flush()
    return sub


async def get(session: AsyncSession, user_id: int, sub_id: int) -> Subscription | None:
    result = await session.scalars(
        select(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
    )
    return result.first()


async def get_by_feed(session: AsyncSession, user_id: int, feed_id: int) -> Subscription | None:
    result = await session.scalars(
        select(Subscription).where(Subscription.user_id == user_id, Subscription.feed_id == feed_id)
    )
    return result.first()


async def count_for_user(session: AsyncSession, user_id: int) -> int:
    """Number of subscriptions a user has (for quota enforcement)."""
    result = await session.scalar(
        select(func.count()).select_from(Subscription).where(Subscription.user_id == user_id)
    )
    return result or 0


async def list_all(session: AsyncSession, user_id: int) -> list[Subscription]:
    result = await session.scalars(
        select(Subscription).where(Subscription.user_id == user_id).order_by(Subscription.id)
    )
    return list(result.all())


async def list_with_feed(
    session: AsyncSession, user_id: int
) -> Sequence[Row[tuple[Subscription, Feed, str | None]]]:
    """Subscriptions joined to their (global) feed for metadata like ``last_error``
    and ``last_fetched_at``, plus the icon's source URL (used to content-version the
    icon URL so a changed icon busts the browser's immutable cache). Shaping in WP-06."""
    result = await session.execute(
        select(Subscription, Feed, Icon.url)
        .join(Feed, Feed.id == Subscription.feed_id)
        .outerjoin(Icon, Icon.id == Feed.icon_id)
        .where(Subscription.user_id == user_id)
        .order_by(Subscription.id)
    )
    return result.all()


async def update(
    session: AsyncSession,
    user_id: int,
    sub_id: int,
    *,
    title_override: str | None = None,
    folder_id: int | None = None,
    set_title_override: bool = False,
    set_folder_id: bool = False,
) -> Subscription | None:
    """Patch a subscription. ``set_*`` flags distinguish "leave unchanged" from
    "explicitly set to NULL" for the nullable fields."""
    sub = await get(session, user_id, sub_id)
    if sub is None:
        return None
    if set_title_override:
        sub.title_override = title_override
    if set_folder_id:
        sub.folder_id = folder_id
    await session.flush()
    return sub


async def delete(session: AsyncSession, user_id: int, sub_id: int) -> bool:
    """Unsubscribe and clean up. Removes the subscription plus this user's read/star
    state for the feed's entries; and if no one is left subscribed, deletes the feed
    itself (its entries + every read/star row cascade). So "delete a feed" really does
    remove all of it, and re-subscribing later starts fresh."""
    feed_id = await session.scalar(
        select(Subscription.feed_id).where(
            Subscription.id == sub_id, Subscription.user_id == user_id
        )
    )
    if feed_id is None:
        return False
    await session.execute(
        sql_delete(Subscription).where(Subscription.id == sub_id, Subscription.user_id == user_id)
    )
    remaining = await session.scalar(
        select(func.count()).select_from(Subscription).where(Subscription.feed_id == feed_id)
    )
    if remaining:
        # Feed still has other subscribers: keep it, drop only this user's state.
        await session.execute(
            sql_delete(EntryState).where(
                EntryState.user_id == user_id,
                EntryState.entry_id.in_(select(Entry.id).where(Entry.feed_id == feed_id)),
            )
        )
    else:
        # Nobody left subscribed → delete the feed; entries + read/star state cascade.
        await session.execute(sql_delete(Feed).where(Feed.id == feed_id))
    return True
