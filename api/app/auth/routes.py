"""Auth & account routes: /config, /me, /tokens, /webhooks/clerk (DESIGN.md §5).

These live inside ``app/auth/`` because /config and the webhook are
Clerk-aware — nothing outside this package may reference Clerk.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook, WebhookVerificationError

from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.store import users as users_store
from app.store.counts import unread_counts

from . import pat
from .clerk import ClerkSettings
from .provider import AuthedUser
from .runtime import current_user

router = APIRouter()

CurrentUser = Annotated[AuthedUser, Depends(current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]


class ConfigResponse(BaseModel):
    auth_mode: str
    clerk_publishable_key: str | None = None


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
    """Public: tells the SPA which auth mode to boot in."""
    mode = get_settings().auth_mode or "unset"
    if mode == "clerk":
        return ConfigResponse(auth_mode=mode, clerk_publishable_key=ClerkSettings().publishable_key)
    return ConfigResponse(auth_mode=mode)


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
        event = Webhook(secret).verify(payload, dict(request.headers))
    except WebhookVerificationError:
        raise ApiError(401, "unauthenticated", "invalid webhook signature") from None

    event_type = event.get("type")
    data = event.get("data") or {}
    clerk_user_id = data.get("id")
    if not isinstance(clerk_user_id, str) or not clerk_user_id:
        return

    if event_type in ("user.created", "user.updated"):
        email = _primary_email(data)
        user = await users_store.get_by_clerk_id(session, clerk_user_id)
        if user is None:
            await users_store.create(session, clerk_user_id=clerk_user_id, email=email)
        else:
            user.email = email
            await session.flush()
    elif event_type == "user.deleted":
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
