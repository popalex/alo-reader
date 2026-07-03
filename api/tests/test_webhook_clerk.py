"""Clerk webhook: svix signature verification + local user sync (created/updated/deleted)."""

import base64
import json
import secrets
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from svix.webhooks import Webhook

from app import db as app_db
from app.auth import pat
from app.models import ApiToken, User
from app.store import users as users_store

WEBHOOK_PATH = "/api/v1/webhooks/clerk"


@pytest.fixture
def webhook_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = "whsec_" + base64.b64encode(secrets.token_bytes(24)).decode()
    monkeypatch.setenv("CLERK_WEBHOOK_SECRET", secret)
    return secret


def signed_headers(secret: str, payload: str) -> dict[str, str]:
    msg_id = "msg_" + secrets.token_hex(8)
    timestamp = datetime.now(UTC)
    signature = Webhook(secret).sign(msg_id=msg_id, timestamp=timestamp, data=payload)
    return {
        "svix-id": msg_id,
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": signature,
        "content-type": "application/json",
    }


def user_event(event_type: str, clerk_id: str, email: str | None = None) -> str:
    data: dict[str, Any] = {"id": clerk_id}
    if email is not None:
        data["primary_email_address_id"] = "em_primary"
        data["email_addresses"] = [
            {"id": "em_other", "email_address": "other@example.com"},
            {"id": "em_primary", "email_address": email},
        ]
    return json.dumps({"type": event_type, "data": data})


async def post_event(client: httpx.AsyncClient, secret: str, payload: str) -> httpx.Response:
    return await client.post(WEBHOOK_PATH, content=payload, headers=signed_headers(secret, payload))


async def test_user_created(api_client: httpx.AsyncClient, webhook_secret: str) -> None:
    payload = user_event("user.created", "user_wh1", "primary@example.com")
    response = await post_event(api_client, webhook_secret, payload)
    assert response.status_code == 204

    async with app_db.get_sessionmaker()() as s:
        user = await users_store.get_by_clerk_id(s, "user_wh1")
    assert user is not None
    assert user.email == "primary@example.com"  # primary picked, not the first entry


async def test_user_updated_and_created_idempotent(
    api_client: httpx.AsyncClient, webhook_secret: str
) -> None:
    await post_event(
        api_client, webhook_secret, user_event("user.created", "user_wh2", "a@example.com")
    )
    # Redelivered create with a new address updates instead of duplicating.
    await post_event(
        api_client, webhook_secret, user_event("user.created", "user_wh2", "b@example.com")
    )
    await post_event(
        api_client, webhook_secret, user_event("user.updated", "user_wh2", "c@example.com")
    )
    async with app_db.get_sessionmaker()() as s:
        count = await s.scalar(
            select(func.count()).select_from(User).where(User.clerk_user_id == "user_wh2")
        )
        user = await users_store.get_by_clerk_id(s, "user_wh2")
    assert count == 1
    assert user is not None and user.email == "c@example.com"


async def test_user_deleted_cascades(api_client: httpx.AsyncClient, webhook_secret: str) -> None:
    await post_event(
        api_client, webhook_secret, user_event("user.created", "user_wh3", "x@example.com")
    )
    async with app_db.get_sessionmaker()() as s, s.begin():
        user = await users_store.get_by_clerk_id(s, "user_wh3")
        assert user is not None
        user_id = user.id
        await pat.create(s, user_id, label="doomed")

    response = await post_event(api_client, webhook_secret, user_event("user.deleted", "user_wh3"))
    assert response.status_code == 204

    async with app_db.get_sessionmaker()() as s:
        assert await users_store.get_by_clerk_id(s, "user_wh3") is None
        tokens = await s.scalar(
            select(func.count()).select_from(ApiToken).where(ApiToken.user_id == user_id)
        )
    assert tokens == 0  # FK cascade wiped the user's tokens


async def test_invalid_signature_rejected(
    api_client: httpx.AsyncClient, webhook_secret: str
) -> None:
    payload = user_event("user.created", "user_forged", "evil@example.com")
    headers = signed_headers(webhook_secret, payload)
    tampered = payload.replace("user_forged", "user_f0rged")
    response = await api_client.post(WEBHOOK_PATH, content=tampered, headers=headers)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"

    async with app_db.get_sessionmaker()() as s:
        assert await users_store.get_by_clerk_id(s, "user_f0rged") is None


async def test_missing_signature_rejected(
    api_client: httpx.AsyncClient, webhook_secret: str
) -> None:
    payload = user_event("user.created", "user_nosig", "x@example.com")
    response = await api_client.post(WEBHOOK_PATH, content=payload)
    assert response.status_code == 401


async def test_unknown_event_acknowledged(
    api_client: httpx.AsyncClient, webhook_secret: str
) -> None:
    payload = json.dumps({"type": "session.created", "data": {"id": "sess_1"}})
    response = await post_event(api_client, webhook_secret, payload)
    assert response.status_code == 204
