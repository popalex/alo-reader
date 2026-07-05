"""Store functions for per-user ``entry_states`` — user-scoped (``user_id`` required).

Upsert follows last-writer-wins on ``changed_at`` (the offline-replay merge key). Full
tie-bias semantics (equal timestamps bias to ``read=true``) are exercised by the state
endpoint in WP-07; this store enforces the newer-or-equal-wins guard.
"""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import case, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Entry, EntryState
from app.store import rowcount


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


async def apply_state_batch(
    session: AsyncSession,
    user_id: int,
    entry_ids: Sequence[int],
    *,
    is_read: bool | None,
    is_starred: bool | None,
    changed_at: datetime,
) -> int:
    """Apply one read/starred change to many entries with last-writer-wins on
    ``changed_at`` (the offline-replay merge key). A strictly-newer write overwrites;
    an equal-timestamp write biases a flag to ``true`` (never downgrades) — so replay
    is idempotent and ties resolve to read/starred=true (DESIGN.md §5). Only the flags
    provided (non-None) are touched. Non-existent entry ids are skipped (INSERT…SELECT
    over ``entries``). Returns the number of rows inserted or updated."""
    if not entry_ids or (is_read is None and is_starred is None):
        return 0

    src = select(
        literal(user_id).label("user_id"),
        Entry.id.label("entry_id"),
        literal(bool(is_read)).label("is_read"),
        literal(bool(is_starred)).label("is_starred"),
        literal(changed_at).label("changed_at"),
    ).where(Entry.id.in_(entry_ids))
    stmt = pg_insert(EntryState).from_select(
        ["user_id", "entry_id", "is_read", "is_starred", "changed_at"], src
    )
    excluded = stmt.excluded
    strictly_newer = EntryState.changed_at < excluded.changed_at

    set_: dict[str, object] = {"changed_at": excluded.changed_at}
    if is_read is not None:
        set_["is_read"] = case(
            (strictly_newer, excluded.is_read),
            else_=or_(EntryState.is_read, excluded.is_read),  # tie → bias true
        )
    if is_starred is not None:
        set_["is_starred"] = case(
            (strictly_newer, excluded.is_starred),
            else_=or_(EntryState.is_starred, excluded.is_starred),  # tie → bias true
        )
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "entry_id"],
        set_=set_,
        where=EntryState.changed_at <= excluded.changed_at,  # newer-or-equal wins
    )
    result = await session.execute(stmt)
    return rowcount(result)
