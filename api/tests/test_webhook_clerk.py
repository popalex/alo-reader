"""Clerk webhook: svix signature verification + local user sync (created/updated/deleted)."""

import base64
import json
import secrets
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook

from app import db as app_db
from app.auth import pat
from app.models import Entry, User
from app.store import entry_states as entry_states_store
from app.store import feeds as feeds_store
from app.store import folders as folders_store
from app.store import subscriptions as subs_store
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


async def _user_owned_tables(session: AsyncSession) -> list[tuple[str, str]]:
    """Every (table, column) with a foreign key onto users.id, read from the catalog.

    Discovered rather than hardcoded on purpose: a later migration that adds a
    user-owned table without ON DELETE CASCADE leaves rows behind on account
    deletion, and the point of this test is to fail then, not to keep passing
    because nobody remembered to extend a list.
    """
    rows = await session.execute(
        text("""
            SELECT tc.table_name, kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON kcu.constraint_name = tc.constraint_name
             AND kcu.table_schema = tc.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = current_schema()
              AND ccu.table_name = 'users'
              AND ccu.column_name = 'id'
            ORDER BY tc.table_name, kcu.column_name
        """)
    )
    return [(r[0], r[1]) for r in rows.all()]


async def _row_counts(
    session: AsyncSession, tables: list[tuple[str, str]], user_id: int
) -> dict[str, int]:
    counts = {}
    for table, column in tables:
        # Identifiers come from the catalog, not from input, so interpolation is safe.
        n = await session.scalar(
            text(f'SELECT count(*) FROM "{table}" WHERE "{column}" = :uid'), {"uid": user_id}
        )
        counts[table] = int(n or 0)
    return counts


async def test_user_deleted_cascades(api_client: httpx.AsyncClient, webhook_secret: str) -> None:
    """Deleting a Clerk user must remove every row that user owns.

    This is the account-deletion obligation, so it is asserted across all four
    user-owned tables rather than the api_tokens one it used to check — and the
    table list is read from the database, so a new one cannot quietly escape it.
    """
    await post_event(
        api_client, webhook_secret, user_event("user.created", "user_wh3", "x@example.com")
    )
    async with app_db.get_sessionmaker()() as s, s.begin():
        user = await users_store.get_by_clerk_id(s, "user_wh3")
        assert user is not None
        user_id = user.id

        # Populate every user-owned table, so the post-delete assertions cannot pass
        # by having had nothing to delete in the first place.
        await pat.create(s, user_id, label="doomed")
        folder = await folders_store.create(s, user_id, name="Doomed")
        feed = await feeds_store.upsert_by_url(s, feed_url="https://cascade.invalid/rss")
        await subs_store.create(s, user_id, feed_id=feed.id, folder_id=folder.id)
        entry = Entry(feed_id=feed.id, guid_hash=b"\x01" * 32, title="doomed entry")
        s.add(entry)
        await s.flush()
        await entry_states_store.upsert(
            s, user_id, entry.id, changed_at=datetime.now(UTC), is_read=True, is_starred=True
        )

    async with app_db.get_sessionmaker()() as s:
        tables = await _user_owned_tables(s)
        before = await _row_counts(s, tables, user_id)

    # The guard that keeps this test honest: every table the cascade is supposed to
    # clear actually had a row to clear.
    assert set(before) == {"api_tokens", "folders", "subscriptions", "entry_states"}, before
    assert all(n > 0 for n in before.values()), f"test did not populate every table: {before}"

    response = await post_event(api_client, webhook_secret, user_event("user.deleted", "user_wh3"))
    assert response.status_code == 204

    async with app_db.get_sessionmaker()() as s:
        assert await users_store.get_by_clerk_id(s, "user_wh3") is None
        after = await _row_counts(s, tables, user_id)
        # Feeds and their entries are shared, not user-owned: deleting this user's
        # last subscription must not rip a feed out from under another subscriber.
        # Nothing is kept, though — losing its last subscriber marks the feed
        # orphaned (trigger, migration 0005) and the worker's GC deletes it, and
        # its entries, once past orphan_grace_days. Assert that second stage is
        # actually armed, or "shared, so we keep it" quietly becomes "we keep it".
        orphaned_at = await s.scalar(
            text("SELECT orphaned_at FROM feeds WHERE feed_url = :u"),
            {"u": "https://cascade.invalid/rss"},
        )

    assert after == dict.fromkeys(before, 0), f"rows left behind after deletion: {after}"
    assert orphaned_at is not None, "feed lost its last subscriber but was not queued for GC"


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


async def test_signed_non_json_body_rejected(
    api_client: httpx.AsyncClient, webhook_secret: str
) -> None:
    """A correctly-signed body still has to be JSON.

    svix 2.0 stopped parsing the payload during verify(), so the route decodes it
    itself. This covers the branch that split off: signature good, body garbage.
    """
    response = await post_event(api_client, webhook_secret, "not json at all")
    assert response.status_code == 400


async def test_signed_json_scalar_acknowledged(
    api_client: httpx.AsyncClient, webhook_secret: str
) -> None:
    # Valid JSON that isn't an object has no event type to act on — ack and drop it
    # rather than raising on .get().
    response = await post_event(api_client, webhook_secret, json.dumps("nope"))
    assert response.status_code == 204


async def test_update_after_delete_does_not_resurrect_the_account(
    api_client: httpx.AsyncClient, webhook_secret: str
) -> None:
    # svix retries for up to a day and does not guarantee ordering, so a user.updated
    # can land after user.deleted. Creating the row from it rebuilds the local identity
    # of an account that no longer exists, and the next JWT carrying that sub would
    # sign in against it.
    await post_event(
        api_client, webhook_secret, user_event("user.created", "user_gone", "gone@example.com")
    )
    await post_event(api_client, webhook_secret, user_event("user.deleted", "user_gone"))

    late = await post_event(
        api_client, webhook_secret, user_event("user.updated", "user_gone", "new@example.com")
    )

    assert late.status_code == 204  # acknowledged, so svix stops retrying
    async with app_db.get_sessionmaker()() as s:
        assert await users_store.get_by_clerk_id(s, "user_gone") is None
