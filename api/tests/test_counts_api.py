"""GET /counts — exact unread counts vs brute force, and cross-tenant (WP-07)."""

import random

import httpx
from sqlalchemy import select

from app import db as app_db
from app.models import Entry, EntryState, Subscription
from tests.apihelpers import seed_feed_with_entries

from .conftest import PatUser, make_pat_user

COUNTS = "/api/v1/counts"
STATE = "/api/v1/entries/state"


async def _brute_force(user_id: int) -> dict[int, int]:
    """Recompute unread-per-subscription from raw rows, independent of the store query."""
    sf = app_db.get_sessionmaker()
    async with sf() as s:
        subs = (
            await s.execute(
                select(Subscription.id, Subscription.feed_id, Subscription.since_entry_id).where(
                    Subscription.user_id == user_id
                )
            )
        ).all()
        read_ids = set(
            (
                await s.scalars(
                    select(EntryState.entry_id).where(
                        EntryState.user_id == user_id, EntryState.is_read.is_(True)
                    )
                )
            ).all()
        )
        out: dict[int, int] = {}
        for sub_id, feed_id, since in subs:
            entry_ids = (
                await s.scalars(select(Entry.id).where(Entry.feed_id == feed_id, Entry.id > since))
            ).all()
            out[sub_id] = sum(1 for eid in entry_ids if eid not in read_ids)
        return out


async def test_counts_match_brute_force_randomized(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    rng = random.Random(1234)
    all_entry_ids: list[int] = []
    for _ in range(5):
        n = rng.randint(2, 8)
        _, ids = await seed_feed_with_entries(pat_user.user_id, n)
        all_entry_ids.extend(ids)

    # Mark a random subset read (some ids repeated is fine; LWW is idempotent).
    to_read = rng.sample(all_entry_ids, k=len(all_entry_ids) // 2)
    if to_read:
        await api_client.post(STATE, json={"ids": to_read, "read": True}, headers=pat_user.headers)

    expected = await _brute_force(pat_user.user_id)
    resp = await api_client.get(COUNTS, headers=pat_user.headers)
    assert resp.status_code == 200
    body = resp.json()

    got = {row["id"]: row["unread"] for row in body["subscriptions"]}
    assert got == expected
    assert body["total_unread"] == sum(expected.values())


async def test_counts_are_per_tenant(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    await seed_feed_with_entries(pat_user.user_id, 4)
    other = await make_pat_user("grace@example.com")

    a = (await api_client.get(COUNTS, headers=pat_user.headers)).json()
    b = (await api_client.get(COUNTS, headers=other.headers)).json()
    assert a["total_unread"] == 4
    assert b["total_unread"] == 0 and b["subscriptions"] == []
