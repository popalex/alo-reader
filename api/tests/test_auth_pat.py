"""Personal access tokens: format, happy path, revocation, deleted user, endpoints."""

import hashlib
from collections.abc import Callable

import httpx
from sqlalchemy import select

from app import db as app_db
from app.auth import pat
from app.models import ApiToken
from app.store import users as users_store

from .conftest import PatUser, make_pat_user


def test_token_format() -> None:
    token = pat.generate_token()
    assert token.startswith("alo_pat_")
    assert len(token) > 40
    assert pat.generate_token() != token
    assert pat.hash_token(token) == hashlib.sha256(token.encode()).digest()
    assert len(pat.hash_token(token)) == 32


async def test_pat_happy_path(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    response = await api_client.get("/api/v1/me", headers=pat_user.headers)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == pat_user.user_id
    assert body["quotas"] == {"subscriptions": 300}
    assert body["counts_summary"] == {"total_unread": 0}

    # Successful auth stamps last_used_at.
    async with app_db.get_sessionmaker()() as s:
        row = await s.scalar(
            select(ApiToken).where(ApiToken.token_hash == pat.hash_token(pat_user.token))
        )
        assert row is not None and row.last_used_at is not None


async def test_garbage_and_missing_bearer(
    api_client: httpx.AsyncClient,
    pat_user: PatUser,
    set_auth_mode: Callable[[str], None],
) -> None:
    set_auth_mode("clerk")  # none-mode would map anonymous requests to the single user
    for headers in (
        {},
        {"Authorization": "Bearer alo_pat_wrong"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer "},
    ):
        response = await api_client.get("/api/v1/me", headers=headers)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthenticated"


async def test_revoked_pat_rejected(
    api_client: httpx.AsyncClient,
    pat_user: PatUser,
    set_auth_mode: Callable[[str], None],
) -> None:
    set_auth_mode("clerk")
    async with app_db.get_sessionmaker()() as s, s.begin():
        tokens = await pat.list_for_user(s, pat_user.user_id)
        assert await pat.delete(s, pat_user.user_id, tokens[0].id)
    response = await api_client.get("/api/v1/me", headers=pat_user.headers)
    assert response.status_code == 401


async def test_deleted_user_pat_rejected(
    api_client: httpx.AsyncClient,
    pat_user: PatUser,
    set_auth_mode: Callable[[str], None],
) -> None:
    set_auth_mode("clerk")
    async with app_db.get_sessionmaker()() as s, s.begin():
        assert await users_store.delete(s, pat_user.user_id)
    response = await api_client.get("/api/v1/me", headers=pat_user.headers)
    assert response.status_code == 401


async def test_token_endpoints(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    created = await api_client.post(
        "/api/v1/tokens", json={"label": "cli"}, headers=pat_user.headers
    )
    assert created.status_code == 201
    token = created.json()["token"]
    assert token.startswith("alo_pat_")

    # The new token authenticates.
    me = await api_client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["id"] == pat_user.user_id

    listing = await api_client.get("/api/v1/tokens", headers=pat_user.headers)
    assert listing.status_code == 200
    rows = listing.json()
    assert [r["label"] for r in rows] == ["test", "cli"]
    for row in rows:
        assert set(row) == {"id", "label", "created_at", "last_used_at"}  # never the secret

    new_id = rows[1]["id"]
    deleted = await api_client.delete(f"/api/v1/tokens/{new_id}", headers=pat_user.headers)
    assert deleted.status_code == 204
    listing = await api_client.get("/api/v1/tokens", headers=pat_user.headers)
    assert [r["label"] for r in listing.json()] == ["test"]

    missing = await api_client.delete(f"/api/v1/tokens/{new_id}", headers=pat_user.headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


async def test_cross_tenant_token_delete(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    other = await make_pat_user("other@example.com")
    async with app_db.get_sessionmaker()() as s:
        victim_token_id = (await pat.list_for_user(s, pat_user.user_id))[0].id

    response = await api_client.delete(f"/api/v1/tokens/{victim_token_id}", headers=other.headers)
    assert response.status_code == 404  # not 403: existence is not revealed

    # Victim's token still works.
    me = await api_client.get("/api/v1/me", headers=pat_user.headers)
    assert me.status_code == 200


async def test_validation_error_envelope(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    response = await api_client.post("/api/v1/tokens", json={}, headers=pat_user.headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
