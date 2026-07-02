"""Basic claim-due-feeds behavior (the worker loop that drives it is WP-05)."""

from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Feed
from app.store import feeds as feeds_store
from tests.factories import make_feed


async def test_claim_due_feeds_leases_and_excludes(session: AsyncSession) -> None:
    # New feeds default next_check_at='epoch' → immediately due.
    f1 = await make_feed(session)
    f2 = await make_feed(session)

    claimed = await feeds_store.claim_due_feeds(session, limit=10)
    claimed_ids = {f.id for f in claimed}
    assert {f1.id, f2.id} <= claimed_ids

    # A second claim returns nothing: the lease (claimed_until in the future) hides them.
    again = await feeds_store.claim_due_feeds(session, limit=10)
    assert again == []


async def test_claim_respects_next_check_at(session: AsyncSession) -> None:
    feed = await make_feed(session)
    # Push next_check_at far into the future → not due.
    await session.execute(
        update(Feed)
        .where(Feed.id == feed.id)
        .values(next_check_at=text("now() + interval '1 hour'"))
    )
    claimed = await feeds_store.claim_due_feeds(session, limit=10)
    assert feed.id not in {f.id for f in claimed}
