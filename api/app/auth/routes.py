"""Auth & account routes: /config, /me, /tokens, /webhooks/clerk (DESIGN.md §5).

These live inside ``app/auth/`` because /config and the webhook are
Clerk-aware — nothing outside this package may reference Clerk.
"""

import json
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import get_settings
from app.deps import CurrentUser, Session
from app.errors import ApiError
from app.store import users as users_store
from app.store.counts import unread_counts

from . import pat
from .clerk import ClerkSettings

router = APIRouter()


class ConfigResponse(BaseModel):
    auth_mode: str
    clerk_publishable_key: str | None = None
    # When true, the SPA lazy-loads the browser OTel SDK and posts spans to otel_traces_url.
    otel_enabled: bool = False
    otel_traces_url: str | None = None


class MeQuotas(BaseModel):
    subscriptions: int


class MeCountsSummary(BaseModel):
    total_unread: int


class MeResponse(BaseModel):
    id: int
    email: str
    quotas: MeQuotas
    counts_summary: MeCountsSummary


class TokenInfo(BaseModel):
    id: int
    label: str
    created_at: datetime
    last_used_at: datetime | None


class CreateTokenRequest(BaseModel):
    label: str


class CreateTokenResponse(BaseModel):
    token: str


@router.get("/config", response_model=ConfigResponse, response_model_exclude_none=True)
async def get_config() -> ConfigResponse:
    """Public: tells the SPA which auth mode to boot in and whether to enable tracing."""
    settings = get_settings()
    mode = settings.auth_mode or "unset"
    otel_enabled = settings.otel_enabled
    otel_traces_url = settings.otel_traces_url if otel_enabled else None
    clerk_key = ClerkSettings().publishable_key if mode == "clerk" else None
    return ConfigResponse(
        auth_mode=mode,
        clerk_publishable_key=clerk_key,
        otel_enabled=otel_enabled,
        otel_traces_url=otel_traces_url,
    )


@router.get("/me", response_model=MeResponse)
async def get_me(user: CurrentUser, session: Session) -> MeResponse:
    counts = await unread_counts(session, user.id)
    return MeResponse(
        id=user.id,
        email=user.email,
        quotas=MeQuotas(subscriptions=user.quota_subs),
        counts_summary=MeCountsSummary(total_unread=counts.total),
    )


@router.get("/tokens", response_model=list[TokenInfo])
async def list_tokens(user: CurrentUser, session: Session) -> list[TokenInfo]:
    rows = await pat.list_for_user(session, user.id)
    return [
        TokenInfo(id=r.id, label=r.label, created_at=r.created_at, last_used_at=r.last_used_at)
        for r in rows
    ]


@router.post("/tokens", response_model=CreateTokenResponse, status_code=201)
async def create_token(
    body: CreateTokenRequest, user: CurrentUser, session: Session
) -> CreateTokenResponse:
    cap = get_settings().quota_api_tokens
    await pat.lock_for_create(session, user.id)  # serialize concurrent creates (no TOCTOU)
    if await pat.count_for_user(session, user.id) >= cap:
        raise ApiError(422, "quota_exceeded", f"API token limit ({cap}) reached")
    _, token = await pat.create(session, user.id, label=body.label)
    return CreateTokenResponse(token=token)  # plaintext shown exactly once


@router.delete("/tokens/{token_id}", status_code=204)
async def delete_token(token_id: int, user: CurrentUser, session: Session) -> None:
    if not await pat.delete(session, user.id, token_id):
        raise ApiError(404, "not_found", "token not found")


@router.post("/webhooks/clerk", status_code=204)
async def clerk_webhook(request: Request, session: Session) -> None:
    """svix-signature-verified user sync: user.created / user.updated / user.deleted."""
    payload = await request.body()
    secret = ClerkSettings().webhook_secret
    if not secret:
        raise ApiError(500, "internal", "webhook secret not configured")
    try:
        # svix 2.x verifies only and returns None, so the payload is decoded below.
        Webhook(secret).verify(payload, dict(request.headers))
    except WebhookVerificationError:
        raise ApiError(401, "unauthenticated", "invalid webhook signature") from None

    try:
        event = json.loads(payload)
    except ValueError:
        raise ApiError(400, "bad_request", "webhook payload is not JSON") from None
    if not isinstance(event, dict):
        return

    event_type = event.get("type")
    data = event.get("data") or {}
    clerk_user_id = data.get("id")
    if not isinstance(clerk_user_id, str) or not clerk_user_id:
        return

    if event_type in ("user.created", "user.updated"):
        email = _primary_email(data)
        user = await users_store.get_by_clerk_id(session, clerk_user_id)
        if user is not None:
            user.email = email
            await session.flush()
        elif event_type == "user.created" and not await users_store.is_clerk_deleted(
            session, clerk_user_id
        ):
            await users_store.create(session, clerk_user_id=clerk_user_id, email=email)
        # A user.updated for a row we do not have is dropped rather than created.
        # svix retries for a day and does not guarantee order, so an update landing
        # after the delete would otherwise rebuild the local identity of an account
        # that no longer exists, and the next JWT carrying that sub would sign in
        # against it. A live user missing locally is handled where it belongs: the
        # JWT path auto-provisions on the next request.
        #
        # A retried user.created landing after the delete is refused the same way,
        # against the deleted_clerk_users tombstone: svix retries for a day without
        # ordering guarantees, and Clerk never reuses a user id.
    elif event_type == "user.deleted":
        # The tombstone goes down whether or not a row is here to remove: the delete
        # may itself be a retry, or may arrive before the create it raced.
        await users_store.mark_clerk_deleted(session, clerk_user_id)
        user = await users_store.get_by_clerk_id(session, clerk_user_id)
        if user is not None:
            # FK ON DELETE CASCADE removes tokens/folders/subscriptions/states.
            await users_store.delete(session, user.id)
    # Unknown event types are acknowledged (204) and ignored.


def _primary_email(data: dict[str, object]) -> str:
    addresses = data.get("email_addresses")
    if not isinstance(addresses, list):
        return ""
    primary_id = data.get("primary_email_address_id")
    first = ""
    for item in addresses:
        if not isinstance(item, dict):
            continue
        email = item.get("email_address")
        if not isinstance(email, str):
            continue
        if not first:
            first = email
        if primary_id is not None and item.get("id") == primary_id:
            return email
    return first
