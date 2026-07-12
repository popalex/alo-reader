"""Stream listing + bounded mark-read endpoints (WP-07)."""

import httpx

from .apihelpers import add_entries, seed_feed_with_entries
from .conftest import PatUser

BASE = "/api/v1/streams"


async def test_list_unread_newest_first(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 5)
    resp = await api_client.get(f"{BASE}/all/entries", headers=pat_user.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert [e["id"] for e in body["entries"]] == sorted(ids, reverse=True)
    first = body["entries"][0]
    assert first["feed_title"] == "Feed" and first["summary"] and first["is_read"] is False


async def test_since_entry_id_hides_pre_subscription(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    # Seed 5 entries but subscribe only as of the 3rd, so entries <= that id are
    # never unread (DESIGN.md §4). We do this in two passes: create the feed with
    # the first 3 entries, subscribe as of the head, then add 2 more.
    feed_id, first3 = await seed_feed_with_entries(pat_user.user_id, 3, since_entry_id=999_999_999)
    later2 = await add_entries(feed_id, 2, start=100)

    # Re-point the subscription's since_entry_id to the current head of first3.
    from sqlalchemy import update

    from app import db as app_db
    from app.models import Subscription

    async with app_db.get_sessionmaker()() as s, s.begin():
        await s.execute(
            update(Subscription)
            .where(Subscription.user_id == pat_user.user_id, Subscription.feed_id == feed_id)
            .values(since_entry_id=first3[-1])
        )

    unread = await api_client.get(
        f"{BASE}/feed/{feed_id}/entries?status=unread", headers=pat_user.headers
    )
    assert [e["id"] for e in unread.json()["entries"]] == sorted(later2, reverse=True)


async def test_status_all_ignores_read_and_cutoff(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 4)
    # Mark two read.
    await api_client.post(
        "/api/v1/entries/state", json={"ids": ids[:2], "read": True}, headers=pat_user.headers
    )
    unread = await api_client.get(f"{BASE}/all/entries?status=unread", headers=pat_user.headers)
    assert {e["id"] for e in unread.json()["entries"]} == set(ids[2:])
    all_ = await api_client.get(f"{BASE}/all/entries?status=all", headers=pat_user.headers)
    assert {e["id"] for e in all_.json()["entries"]} == set(ids)


async def test_cursor_pagination_gap_free_during_inserts(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    feed_id, first = await seed_feed_with_entries(pat_user.user_id, 6)
    h = pat_user.headers

    page1 = (await api_client.get(f"{BASE}/all/entries?status=all&limit=3", headers=h)).json()
    assert [e["id"] for e in page1["entries"]] == list(reversed(first[3:]))
    assert page1["next_cursor"]  # opaque keyset cursor

    # New entries arrive mid-pagination; the keyset cursor keeps page 2 stable.
    await add_entries(feed_id, 4, start=100)
    page2 = (
        await api_client.get(
            f"{BASE}/all/entries?status=all&limit=3&cursor={page1['next_cursor']}", headers=h
        )
    ).json()
    assert [e["id"] for e in page2["entries"]] == list(reversed(first[:3]))

    ids = [e["id"] for e in page1["entries"]] + [e["id"] for e in page2["entries"]]
    assert len(ids) == len(set(ids))  # no duplicates
    assert ids == sorted(ids, reverse=True)  # strictly newest-first


async def test_feed_folder_and_starred_streams(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    h = pat_user.headers
    folder_id = (await api_client.post("/api/v1/folders", json={"name": "F"}, headers=h)).json()[
        "id"
    ]
    feed_a, ids_a = await seed_feed_with_entries(pat_user.user_id, 3, folder_id=folder_id)
    feed_b, ids_b = await seed_feed_with_entries(pat_user.user_id, 2)

    only_a = await api_client.get(f"{BASE}/feed/{feed_a}/entries?status=all", headers=h)
    assert {e["id"] for e in only_a.json()["entries"]} == set(ids_a)

    folder = await api_client.get(f"{BASE}/folder/{folder_id}/entries?status=all", headers=h)
    assert {e["id"] for e in folder.json()["entries"]} == set(ids_a)

    # Star one entry, then the starred stream shows exactly it.
    await api_client.post(
        "/api/v1/entries/state", json={"ids": [ids_b[0]], "starred": True}, headers=h
    )
    starred = await api_client.get(f"{BASE}/starred/entries?status=all", headers=h)
    assert [e["id"] for e in starred.json()["entries"]] == [ids_b[0]]


async def test_invalid_stream_is_400(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    resp = await api_client.get(f"{BASE}/bogus/entries", headers=pat_user.headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"


async def test_limit_over_max_is_422(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    resp = await api_client.get(f"{BASE}/all/entries?limit=201", headers=pat_user.headers)
    assert resp.status_code == 422


async def test_mark_read_is_bounded(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 5)
    h = pat_user.headers

    # Mark everything up to (and including) the 3rd entry read.
    resp = await api_client.post(f"{BASE}/all/mark-read", json={"max_entry_id": ids[2]}, headers=h)
    assert resp.status_code == 200 and resp.json()["updated"] == 3

    unread = await api_client.get(f"{BASE}/all/entries?status=unread", headers=h)
    assert {e["id"] for e in unread.json()["entries"]} == {ids[3], ids[4]}  # newer stay unread

    # Idempotent: a second identical call flips nothing.
    again = await api_client.post(f"{BASE}/all/mark-read", json={"max_entry_id": ids[2]}, headers=h)
    assert again.json()["updated"] == 0


async def test_mark_read_no_bound_marks_whole_stream(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    # "Mark all read": no max_entry_id → the entire stream, regardless of id (the row
    # order is by publish date now, so the top row's id is not the max id).
    await seed_feed_with_entries(pat_user.user_id, 5)
    h = pat_user.headers

    resp = await api_client.post(f"{BASE}/all/mark-read", json={}, headers=h)
    assert resp.status_code == 200 and resp.json()["updated"] == 5

    unread = await api_client.get(f"{BASE}/all/entries?status=unread", headers=h)
    assert unread.json()["entries"] == []
