"""Store functions for the ``users`` identity table.

Users are the identity root; these functions are keyed by ``id``/``clerk_user_id``
rather than scoped by ``user_id`` (there is nothing above a user to scope to).
"""

from sqlalchemy import delete as sql_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.store import rowcount


async def create(
    session: AsyncSession,
    *,
    clerk_user_id: str | None = None,
    email: str = "",
    quota_subs: int = 300,
) -> User:
    user = User(clerk_user_id=clerk_user_id, email=email, quota_subs=quota_subs)
    session.add(user)
    await session.flush()
    return user


async def get(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_by_clerk_id(session: AsyncSession, clerk_user_id: str) -> User | None:
    result = await session.scalars(select(User).where(User.clerk_user_id == clerk_user_id))
    return result.first()


async def delete(session: AsyncSession, user_id: int) -> bool:
    result = await session.execute(sql_delete(User).where(User.id == user_id))
    return rowcount(result) > 0
