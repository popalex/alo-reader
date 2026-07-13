"""Subscription endpoints: CRUD, quota, dup, refresh-rate, cross-tenant (WP-06)."""

import httpx
import pytest
from sqlalchemy import update

from app import db as app_db
from app.models import Feed, User
from app.store import entries as entries_store
from app.store import feeds as feeds_store

from .conftest import PatUser, make_pat_user

SUBS = "/api/v1/subscriptions"
FOLDERS = "/api/v1/folders"


async def _set_quota(user_id: int, quota: int) -> None:
    async with app_db.get_sessionmaker()() as s, s.begin():
        await s.execute(update(User).where(User.id == user_id).values(quota_subs=quota))


async def test_subscribe_creates_feed_and_queues_poll(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    resp = await api_client.post(
        SUBS, json={"feed_url": "https://Example.com/Feed.xml"}, headers=pat_user.headers
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["feed_id"] and body["folder_id"] is None
    assert body["icon_url"] is None and body["last_error"] is None

    async with app_db.get_sessionmaker()() as s:
        # URL normalized (scheme/host lowercased) and reused as the one global feed.
        feed = await feeds_store.get_by_url(s, "https://example.com/Feed.xml")
        assert feed is not None and feed.id == body["feed_id"]
        # Queued for an immediate poll.
        assert feed.next_check_at is not None


async def test_since_entry_id_set_to_feed_head(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    sf = app_db.get_sessionmaker()
    # A feed that already has 3 archived entries at subscribe time.
    async with sf() as s, s.begin():
        feed = await feeds_store.create(s, feed_url="https://arch.example/rss")
        await entries_store.insert_batch(
            s, feed.id, [{"guid_hash": bytes([i]), "title": f"e{i}"} for i in range(3)]
        )
    async with sf() as s:
        head = await entries_store.max_id_for_feed(s, feed.id)

    resp = await api_client.post(
        SUBS, json={"feed_url": "https://arch.example/rss"}, headers=pat_user.headers
    )
    assert resp.status_code == 201
    async with sf() as s:
        from app.store import subscriptions as subs_store

        sub = await subs_store.get_by_feed(s, pat_user.user_id, feed.id)
        assert sub is not None and sub.since_entry_id == head  # archive not dumped as unread


async def test_duplicate_subscription_is_409(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    payload = {"feed_url": "https://dup.example/rss"}
    first = await api_client.post(SUBS, json=payload, headers=pat_user.headers)
    assert first.status_code == 201
    second = await api_client.post(SUBS, json=payload, headers=pat_user.headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "conflict"


async def test_quota_exceeded_is_422(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    await _set_quota(pat_user.user_id, 1)
    ok = await api_client.post(
        SUBS, json={"feed_url": "https://a.example/rss"}, headers=pat_user.headers
    )
    assert ok.status_code == 201
    over = await api_client.post(
        SUBS, json={"feed_url": "https://b.example/rss"}, headers=pat_user.headers
    )
    assert over.status_code == 422
    assert over.json()["error"]["code"] == "quota_exceeded"


async def test_invalid_feed_url_is_400(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    resp = await api_client.post(SUBS, json={"feed_url": "not-a-url"}, headers=pat_user.headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"


async def test_list_includes_feed_metadata(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    created = await api_client.post(
        SUBS, json={"feed_url": "https://meta.example/rss"}, headers=pat_user.headers
    )
    feed_id = created.json()["feed_id"]
    # Simulate a poll error on the global feed.
    async with app_db.get_sessionmaker()() as s, s.begin():
        await s.execute(
            update(Feed).where(Feed.id == feed_id).values(last_error="boom", title="Meta Feed")
        )

    listed = await api_client.get(SUBS, headers=pat_user.headers)
    row = listed.json()[0]
    assert row["title"] == "Meta Feed"
    assert row["last_error"] == "boom"


async def test_patch_title_and_folder_move(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    h = pat_user.headers
    sub_id = (
        await api_client.post(SUBS, json={"feed_url": "https://p.example/rss"}, headers=h)
    ).json()["id"]
    folder_id = (await api_client.post(FOLDERS, json={"name": "Box"}, headers=h)).json()["id"]

    patched = await api_client.patch(
        f"{SUBS}/{sub_id}", json={"title_override": "My Title", "folder_id": folder_id}, headers=h
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "My Title"
    assert patched.json()["folder_id"] == folder_id

    # Explicit null clears the override + removes from folder.
    cleared = await api_client.patch(
        f"{SUBS}/{sub_id}", json={"title_override": None, "folder_id": None}, headers=h
    )
    assert cleared.json()["folder_id"] is None


async def test_patch_into_foreign_folder_is_404(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    sub_id = (
        await api_client.post(
            SUBS, json={"feed_url": "https://q.example/rss"}, headers=pat_user.headers
        )
    ).json()["id"]
    other = await make_pat_user("carol@example.com")
    foreign_folder = (
        await api_client.post(FOLDERS, json={"name": "Carol's"}, headers=other.headers)
    ).json()["id"]

    resp = await api_client.patch(
        f"{SUBS}/{sub_id}", json={"folder_id": foreign_folder}, headers=pat_user.headers
    )
    assert resp.status_code == 404


async def test_delete_subscription(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    sub_id = (
        await api_client.post(
            SUBS, json={"feed_url": "https://d.example/rss"}, headers=pat_user.headers
        )
    ).json()["id"]
    assert (
        await api_client.delete(f"{SUBS}/{sub_id}", headers=pat_user.headers)
    ).status_code == 204
    assert (await api_client.get(SUBS, headers=pat_user.headers)).json() == []


async def test_subscribe_seeds_placeholder_title(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    # A new feed shows the provided title immediately (before the worker polls), so
    # the sidebar isn't "Untitled feed" until the first fetch.
    resp = await api_client.post(
        SUBS,
        json={"feed_url": "https://titled.example/rss", "title": "My Podcast"},
        headers=pat_user.headers,
    )
    assert resp.status_code == 201
    assert resp.json()["title"] == "My Podcast"


async def test_refresh_rate_limited(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    sub_id = (
        await api_client.post(
            SUBS, json={"feed_url": "https://r.example/rss"}, headers=pat_user.headers
        )
    ).json()["id"]

    first = await api_client.post(f"{SUBS}/{sub_id}/refresh", headers=pat_user.headers)
    assert first.status_code == 202
    assert first.json()["status"] == "queued"

    second = await api_client.post(f"{SUBS}/{sub_id}/refresh", headers=pat_user.headers)
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"


@pytest.mark.parametrize("method", ["get", "patch", "delete", "refresh"])
async def test_cross_tenant_subscription_is_404(
    api_client: httpx.AsyncClient, pat_user: PatUser, method: str
) -> None:
    sub_id = (
        await api_client.post(
            SUBS, json={"feed_url": "https://secret.example/rss"}, headers=pat_user.headers
        )
    ).json()["id"]
    other = await make_pat_user("dave@example.com")
    h = other.headers

    # User B never sees A's subscription in a listing...
    assert (await api_client.get(SUBS, headers=h)).json() == []
    # ...and every id-addressed operation is a 404, not a 403.
    if method == "patch":
        resp = await api_client.patch(f"{SUBS}/{sub_id}", json={"title_override": "x"}, headers=h)
    elif method == "delete":
        resp = await api_client.delete(f"{SUBS}/{sub_id}", headers=h)
    elif method == "refresh":
        resp = await api_client.post(f"{SUBS}/{sub_id}/refresh", headers=h)
    else:
        resp = await api_client.patch(f"{SUBS}/{sub_id}", json={}, headers=h)
    assert resp.status_code == 404
