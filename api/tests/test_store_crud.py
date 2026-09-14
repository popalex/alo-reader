"""CRUD + cross-tenant isolation for the store layer."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.store import entry_states as states_store
from app.store import feeds as feeds_store
from app.store import folders as folders_store
from app.store import subscriptions as subs_store
from app.store import users as users_store
from tests.factories import add_entries, make_feed, make_subscription, make_user


async def test_user_create_get_delete(session: AsyncSession) -> None:
    user = await make_user(session, clerk_user_id="clerk_1")
    assert user.id is not None
    assert (await users_store.get(session, user.id)).id == user.id  # type: ignore[union-attr]
    assert (await users_store.get_by_clerk_id(session, "clerk_1")).id == user.id  # type: ignore[union-attr]
    assert await users_store.delete(session, user.id) is True
    assert await users_store.get(session, user.id) is None


async def test_feed_upsert_dedupes(session: AsyncSession) -> None:
    a = await feeds_store.upsert_by_url(session, feed_url="http://x.com/f.xml")
    b = await feeds_store.upsert_by_url(session, feed_url="http://x.com/f.xml")
    assert a.id == b.id


async def test_folder_crud_and_isolation(session: AsyncSession) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    folder = await folders_store.create(session, alice.id, name="News", position=1)

    # Owner sees it; other tenant does not (returns None, not another user's row).
    assert (await folders_store.get(session, alice.id, folder.id)).id == folder.id  # type: ignore[union-attr]
    assert await folders_store.get(session, bob.id, folder.id) is None
    assert [f.id for f in await folders_store.list_all(session, bob.id)] == []

    # Cross-tenant update/delete are no-ops.
    assert await folders_store.update(session, bob.id, folder.id, name="Hacked") is None
    assert await folders_store.delete(session, bob.id, folder.id) is False
    assert (await folders_store.get(session, alice.id, folder.id)).name == "News"  # type: ignore[union-attr]

    updated = await folders_store.update(session, alice.id, folder.id, name="Tech")
    assert updated is not None and updated.name == "Tech"
    assert await folders_store.delete(session, alice.id, folder.id) is True


async def test_subscription_crud_and_isolation(session: AsyncSession) -> None:
    alice = await make_user(session)
    bob = await make_user(session)
    feed = await make_feed(session)
    sub = await make_subscription(session, alice, feed)

    assert (await subs_store.get(session, alice.id, sub.id)).id == sub.id  # type: ignore[union-attr]
    assert await subs_store.get(session, bob.id, sub.id) is None
    assert await subs_store.delete(session, bob.id, sub.id) is False

    moved = await subs_store.update(
        session, alice.id, sub.id, title_override="Custom", set_title_override=True
    )
    assert moved is not None and moved.title_override == "Custom"
    assert await subs_store.delete(session, alice.id, sub.id) is True


async def test_upsert_tie_does_not_downgrade_a_flag(session: AsyncSession) -> None:
    # apply_state_batch biases an equal-timestamp write to true, so a replayed offline
    # change can never un-read something. upsert assigned the incoming value outright,
    # so on the same table the merge result depended on which writer ran.
    user = await make_user(session)
    feed = await make_feed(session)
    await make_subscription(session, user, feed)
    entry = (await add_entries(session, feed, 1))[0]
    when = datetime.now(UTC)

    await states_store.upsert(session, user.id, entry.id, changed_at=when, is_read=True)
    await states_store.upsert(session, user.id, entry.id, changed_at=when, is_read=False)

    row = await states_store.get(session, user.id, entry.id)
    assert row is not None and row.is_read is True
