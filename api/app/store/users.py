"""Store functions for the ``users`` identity table.

Users are the identity root; these functions are keyed by ``id``/``clerk_user_id``
rather than scoped by ``user_id`` (there is nothing above a user to scope to).
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete as sql_delete
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeletedClerkUser, User
from app.store import rowcount


async def lock_row(session: AsyncSession, user_id: int) -> None:
    """Take a transaction-scoped ``FOR UPDATE`` lock on the user's row so concurrent
    per-user quota checks serialize: without it two simultaneous creates can both pass
    a count-based cap check (TOCTOU) and overshoot. Released automatically at commit."""
    await session.execute(text("SELECT 1 FROM users WHERE id = :uid FOR UPDATE"), {"uid": user_id})


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


async def mark_clerk_deleted(session: AsyncSession, clerk_user_id: str) -> None:
    """Record that this Clerk id was deleted, so a retried webhook cannot recreate it."""
    await session.execute(
        pg_insert(DeletedClerkUser)
        .values(clerk_user_id=clerk_user_id)
        .on_conflict_do_nothing(index_elements=["clerk_user_id"])
    )


async def is_clerk_deleted(session: AsyncSession, clerk_user_id: str) -> bool:
    return (
        await session.scalar(
            select(DeletedClerkUser.clerk_user_id).where(
                DeletedClerkUser.clerk_user_id == clerk_user_id
            )
        )
    ) is not None


async def purge_deletion_tombstones(session: AsyncSession, *, older_than: timedelta) -> int:
    """Drop tombstones past svix's retry window; they have nothing left to protect."""
    result = await session.execute(
        sql_delete(DeletedClerkUser).where(
            DeletedClerkUser.deleted_at < datetime.now(UTC) - older_than
        )
    )
    return rowcount(result)


async def delete(session: AsyncSession, user_id: int) -> bool:
    result = await session.execute(sql_delete(User).where(User.id == user_id))
    return rowcount(result) > 0
