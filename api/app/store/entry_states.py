"""Store functions for per-user ``entry_states`` — user-scoped (``user_id`` required).

Upsert follows last-writer-wins on ``changed_at`` (the offline-replay merge key). Full
tie-bias semantics (equal timestamps bias to ``read=true``) are exercised by the state
endpoint in WP-07; this store enforces the newer-or-equal-wins guard.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EntryState


async def get(session: AsyncSession, user_id: int, entry_id: int) -> EntryState | None:
    return await session.get(EntryState, (user_id, entry_id))


async def upsert(
    session: AsyncSession,
    user_id: int,
    entry_id: int,
    *,
    changed_at: datetime,
    is_read: bool | None = None,
    is_starred: bool | None = None,
) -> EntryState | None:
    """Insert or update a state row. Only the flags provided (non-None) are written;
    the update applies only when the incoming ``changed_at`` is newer-or-equal to the
    stored one (LWW)."""
    stmt = pg_insert(EntryState).values(
        user_id=user_id,
        entry_id=entry_id,
        is_read=bool(is_read) if is_read is not None else False,
        is_starred=bool(is_starred) if is_starred is not None else False,
        changed_at=changed_at,
    )
    set_: dict[str, object] = {"changed_at": stmt.excluded.changed_at}
    if is_read is not None:
        set_["is_read"] = stmt.excluded.is_read
    if is_starred is not None:
        set_["is_starred"] = stmt.excluded.is_starred
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "entry_id"],
        set_=set_,
        where=EntryState.changed_at <= stmt.excluded.changed_at,
    )
    await session.execute(stmt)
    result = await session.scalars(
        select(EntryState).where(EntryState.user_id == user_id, EntryState.entry_id == entry_id)
    )
    return result.first()
