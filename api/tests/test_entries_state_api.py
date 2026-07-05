"""Entry detail + per-user state writes: LWW, tie-bias, cross-tenant (WP-07)."""

from datetime import UTC, datetime, timedelta

import httpx

from app import db as app_db
from app.store import entry_states as states_store
from tests.apihelpers import seed_feed_with_entries

from .conftest import PatUser, make_pat_user

STATE = "/api/v1/entries/state"


async def _state(user_id: int, entry_id: int) -> tuple[bool, bool] | None:
    async with app_db.get_sessionmaker()() as s:
        row = await states_store.get(s, user_id, entry_id)
        return None if row is None else (row.is_read, row.is_starred)


# ── GET /entries/{id} ────────────────────────────────────────────────────────


async def test_get_entry_returns_content_html(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 1)
    resp = await api_client.get(f"/api/v1/entries/{ids[0]}", headers=pat_user.headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == ids[0]
    assert "<p>" in body["content_html"]
    assert body["is_read"] is False and body["is_starred"] is False


async def test_get_missing_entry_is_404(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    resp = await api_client.get("/api/v1/entries/999999", headers=pat_user.headers)
    assert resp.status_code == 404


async def test_get_entry_cross_tenant_is_404(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 1)
    other = await make_pat_user("erin@example.com")
    # User B isn't subscribed to A's feed → the entry id reads as missing.
    resp = await api_client.get(f"/api/v1/entries/{ids[0]}", headers=other.headers)
    assert resp.status_code == 404


# ── POST /entries/state ──────────────────────────────────────────────────────


async def test_state_marks_read_and_reports_updated(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 3)
    resp = await api_client.post(STATE, json={"ids": ids, "read": True}, headers=pat_user.headers)
    assert resp.status_code == 200 and resp.json()["updated"] == 3
    assert await _state(pat_user.user_id, ids[0]) == (True, False)


async def test_state_skips_nonexistent_ids(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 1)
    resp = await api_client.post(
        STATE, json={"ids": [ids[0], 999999], "read": True}, headers=pat_user.headers
    )
    assert resp.json()["updated"] == 1  # the bogus id is silently skipped


async def test_lww_replay_is_idempotent(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 1)
    t = datetime.now(UTC).isoformat()
    payload = {"ids": ids, "read": True, "changed_at": t}
    await api_client.post(STATE, json=payload, headers=pat_user.headers)
    await api_client.post(STATE, json=payload, headers=pat_user.headers)  # replay
    assert await _state(pat_user.user_id, ids[0]) == (True, False)


async def test_older_write_does_not_override(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 1)
    now = datetime.now(UTC)
    # A newer write marks it read...
    await api_client.post(
        STATE,
        json={"ids": ids, "read": True, "changed_at": now.isoformat()},
        headers=pat_user.headers,
    )
    # ...an older write trying to unread it is ignored (LWW).
    old = (now - timedelta(hours=1)).isoformat()
    await api_client.post(
        STATE, json={"ids": ids, "read": False, "changed_at": old}, headers=pat_user.headers
    )
    assert await _state(pat_user.user_id, ids[0]) == (True, False)


async def test_equal_timestamp_ties_bias_to_read_true(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 1)
    t = datetime.now(UTC).isoformat()
    await api_client.post(
        STATE, json={"ids": ids, "read": True, "changed_at": t}, headers=pat_user.headers
    )
    # Same timestamp, read=false — the tie must not downgrade read to false.
    await api_client.post(
        STATE, json={"ids": ids, "read": False, "changed_at": t}, headers=pat_user.headers
    )
    assert await _state(pat_user.user_id, ids[0]) == (True, False)


async def test_state_requires_a_flag_422(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 1)
    resp = await api_client.post(STATE, json={"ids": ids}, headers=pat_user.headers)
    assert resp.status_code == 422


async def test_state_too_many_ids_422(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    resp = await api_client.post(
        STATE, json={"ids": list(range(1, 1002)), "read": True}, headers=pat_user.headers
    )
    assert resp.status_code == 422


async def test_state_cross_tenant_isolation(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    _, ids = await seed_feed_with_entries(pat_user.user_id, 1)
    entry_id = ids[0]
    # A marks it read.
    await api_client.post(STATE, json={"ids": [entry_id], "read": True}, headers=pat_user.headers)

    # B sets its own state (read=false) on the same entry id.
    other = await make_pat_user("frank@example.com")
    await api_client.post(STATE, json={"ids": [entry_id], "read": False}, headers=other.headers)

    # Direct DB assertion: each user has their own row; B never touched A's.
    assert await _state(pat_user.user_id, entry_id) == (True, False)
    assert await _state(other.user_id, entry_id) == (False, False)
