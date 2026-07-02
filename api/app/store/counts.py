"""Unread counts — user-scoped (``user_id`` required).

Exact, index-backed counts per DESIGN.md §4: an entry is unread for a subscription
when its ``id > subscription.since_entry_id`` and there is no ``entry_states`` row
marking it read for that user. Counts are computed from indexes, never counters.
"""

from dataclasses import dataclass, field

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models import Entry, EntryState, Subscription


@dataclass
class UnreadCounts:
    total: int = 0
    per_subscription: dict[int, int] = field(default_factory=dict)


async def unread_counts(session: AsyncSession, user_id: int) -> UnreadCounts:
    es = aliased(EntryState)
    stmt = (
        select(
            Subscription.id,
            func.count(Entry.id).filter(es.entry_id.is_(None)).label("unread"),
        )
        .select_from(Subscription)
        .outerjoin(
            Entry,
            and_(
                Entry.feed_id == Subscription.feed_id,
                Entry.id > Subscription.since_entry_id,
            ),
        )
        .outerjoin(
            es,
            and_(
                es.entry_id == Entry.id,
                es.user_id == user_id,
                es.is_read.is_(True),
            ),
        )
        .where(Subscription.user_id == user_id)
        .group_by(Subscription.id)
    )
    result = await session.execute(stmt)
    counts = UnreadCounts()
    for sub_id, unread in result.all():
        counts.per_subscription[sub_id] = unread
        counts.total += unread
    return counts
