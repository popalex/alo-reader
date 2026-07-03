"""Store functions for ``folders`` — all user-scoped (``user_id`` required)."""

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Folder
from app.store import rowcount


async def create(session: AsyncSession, user_id: int, *, name: str, position: int = 0) -> Folder:
    folder = Folder(user_id=user_id, name=name, position=position)
    session.add(folder)
    await session.flush()
    return folder


async def get(session: AsyncSession, user_id: int, folder_id: int) -> Folder | None:
    result = await session.scalars(
        select(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
    )
    return result.first()


async def list_all(session: AsyncSession, user_id: int) -> list[Folder]:
    result = await session.scalars(
        select(Folder).where(Folder.user_id == user_id).order_by(Folder.position, Folder.id)
    )
    return list(result.all())


async def update(
    session: AsyncSession,
    user_id: int,
    folder_id: int,
    *,
    name: str | None = None,
    position: int | None = None,
) -> Folder | None:
    folder = await get(session, user_id, folder_id)
    if folder is None:
        return None
    if name is not None:
        folder.name = name
    if position is not None:
        folder.position = position
    await session.flush()
    return folder


async def delete(session: AsyncSession, user_id: int, folder_id: int) -> bool:
    result = await session.execute(
        sql_delete(Folder).where(Folder.id == folder_id, Folder.user_id == user_id)
    )
    return rowcount(result) > 0
