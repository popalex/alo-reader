"""Concurrent quota enforcement (M4): the per-user subscription cap must hold under
two simultaneous creates. Without the ``users.lock_row`` FOR UPDATE guard, both
requests pass the count check (TOCTOU) and overshoot the cap.
"""

import asyncio

import httpx

from app import db as app_db
from app.auth import pat
from app.store import users as users_store

SUBS = "/api/v1/subscriptions"


async def _user_with_quota(quota: int, email: str) -> dict[str, str]:
    async with app_db.get_sessionmaker()() as s, s.begin():
        user = await users_store.create(s, email=email, quota_subs=quota)
        _, token = await pat.create(s, user.id, label="test")
    return {"Authorization": f"Bearer {token}"}


async def test_concurrent_subscribe_respects_quota(
    api_client: httpx.AsyncClient, api_db: str
) -> None:
    headers = await _user_with_quota(1, "quota1@example.com")

    # Two simultaneous subscribes to different feeds; the cap is 1.
    r1, r2 = await asyncio.gather(
        api_client.post(SUBS, json={"feed_url": "https://a.example/rss"}, headers=headers),
        api_client.post(SUBS, json={"feed_url": "https://b.example/rss"}, headers=headers),
    )

    assert sorted([r1.status_code, r2.status_code]) == [201, 422]
    over = r1 if r1.status_code == 422 else r2
    assert over.json()["error"]["code"] == "quota_exceeded"

    # Exactly one subscription was created — the cap held.
    listing = (await api_client.get(SUBS, headers=headers)).json()
    assert len(listing) == 1
