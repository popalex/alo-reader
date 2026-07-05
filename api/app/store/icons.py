"""Store functions for the global ``icons`` table (favicons, deduped by URL)."""

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Feed, Icon


async def get(session: AsyncSession, icon_id: int) -> Icon | None:
    return await session.get(Icon, icon_id)


async def get_or_create(session: AsyncSession, *, url: str, mime: str, data: bytes) -> Icon:
    """Return the existing icon for ``url`` or insert one. Icons are global and
    deduped by source URL, so many feeds can share one favicon row."""
    stmt = (
        pg_insert(Icon)
        .values(url=url, mime=mime, data=data)
        .on_conflict_do_nothing(index_elements=["url"])
        .returning(Icon)
    )
    inserted = (await session.scalars(stmt)).first()
    if inserted is not None:
        return inserted
    existing = (await session.scalars(select(Icon).where(Icon.url == url))).first()
    assert existing is not None  # conflict implies a row exists
    return existing


async def set_feed_icon(session: AsyncSession, feed_id: int, icon_id: int) -> None:
    await session.execute(update(Feed).where(Feed.id == feed_id).values(icon_id=icon_id))
