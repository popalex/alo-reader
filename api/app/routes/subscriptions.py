"""Subscription CRUD + manual refresh (DESIGN.md §5).

Subscriptions are user-scoped; feeds are global and deduped. Subscribing reuses (or
creates) the one global ``feeds`` row for a URL, queues it for an immediate poll,
and pins ``since_entry_id`` to the feed's current head so the existing archive is
never dumped on the new subscriber as unread (DESIGN.md §4). Every id lookup is
tenant-scoped: another user's id reads as 404, never 403.
"""

import hashlib
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.ratelimit import Cooldown
from app.config import get_settings
from app.deps import CurrentUser, Session
from app.errors import ApiError
from app.models import Feed, Subscription
from app.store import entries as entries_store
from app.store import feeds as feeds_store
from app.store import folders as folders_store
from app.store import subscriptions as subs_store
from app.store import users as users_store

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


class SubscriptionResponse(BaseModel):
    id: int
    feed_id: int
    title: str
    feed_url: str  # the RSS/Atom URL (shown read-only in feed settings)
    site_url: str | None
    folder_id: int | None
    icon_url: str | None  # populated in WP-08 (icons); always null for now
    last_error: str | None
    last_fetched_at: datetime | None


class CreateSubscriptionRequest(BaseModel):
    feed_url: str = Field(min_length=1, max_length=2048)
    folder_id: int | None = None
    # Optional placeholder title (e.g. the discovered feed's title) so a brand-new
    # feed shows a real name immediately instead of "Untitled" until the worker polls.
    # Only seeds a newly-created feed; the worker overwrites it with the real title.
    title: str | None = Field(default=None, max_length=200)


class UpdateSubscriptionRequest(BaseModel):
    title_override: str | None = Field(default=None, max_length=200)
    folder_id: int | None = None


class RefreshResponse(BaseModel):
    status: str


_refresh_cooldown = Cooldown()


def normalize_feed_url(raw: str) -> str:
    """Canonicalize a feed URL so equivalent inputs dedupe to one global feed."""
    parts = urlsplit(raw.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.netloc:
        raise ApiError(400, "invalid_request", "feed_url must be an absolute http(s) URL")
    return urlunsplit((scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))


def _icon_url(icon_id: int | None, source_url: str | None) -> str | None:
    """The served icon URL, content-versioned by a hash of the icon's source URL.
    Icons are cached ``immutable``, but an icon id can be reused for different content
    (e.g. after a DB reset, or favicon→artwork); the ``?v=`` makes a changed icon a
    new URL so the browser doesn't serve a stale one."""
    if icon_id is None:
        return None
    if source_url:
        ver = hashlib.sha1(source_url.encode(), usedforsecurity=False).hexdigest()[:8]
        return f"/api/v1/icons/{icon_id}?v={ver}"
    return f"/api/v1/icons/{icon_id}"


def _shape(
    sub: Subscription, feed: Feed, icon_source_url: str | None = None
) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=sub.id,
        feed_id=sub.feed_id,
        title=sub.title_override or feed.title,
        feed_url=feed.feed_url,
        site_url=feed.site_url,
        folder_id=sub.folder_id,
        icon_url=_icon_url(feed.icon_id, icon_source_url),
        last_error=feed.last_error,
        last_fetched_at=feed.last_fetched_at,
    )


async def _require_own_folder(session: AsyncSession, user_id: int, folder_id: int) -> None:
    if await folders_store.get(session, user_id, folder_id) is None:
        raise ApiError(404, "not_found", "folder not found")


@router.get("", response_model=list[SubscriptionResponse])
async def list_subscriptions(user: CurrentUser, session: Session) -> list[SubscriptionResponse]:
    rows = await subs_store.list_with_feed(session, user.id)
    return [_shape(sub, feed, icon_src) for sub, feed, icon_src in rows]


@router.post("", response_model=SubscriptionResponse, status_code=201)
async def create_subscription(
    body: CreateSubscriptionRequest, user: CurrentUser, session: Session
) -> SubscriptionResponse:
    # Serialize the count-based quota check against concurrent creates (TOCTOU), the
    # same guard the API-token cap uses — otherwise two simultaneous subscribes to
    # different feeds can both pass and overshoot quota_subs.
    await users_store.lock_row(session, user.id)
    if await subs_store.count_for_user(session, user.id) >= user.quota_subs:
        raise ApiError(422, "quota_exceeded", f"subscription limit ({user.quota_subs}) reached")

    feed_url = normalize_feed_url(body.feed_url)
    if body.folder_id is not None:
        await _require_own_folder(session, user.id, body.folder_id)

    feed = await feeds_store.upsert_by_url(
        session, feed_url=feed_url, title=(body.title or "").strip()
    )
    if await subs_store.get_by_feed(session, user.id, feed.id) is not None:
        raise ApiError(409, "conflict", "already subscribed to this feed")

    since = await entries_store.max_id_for_feed(session, feed.id)
    try:
        sub = await subs_store.create(
            session, user.id, feed_id=feed.id, folder_id=body.folder_id, since_entry_id=since
        )
        await session.flush()
    except IntegrityError:  # racing duplicate on the (user_id, feed_id) unique index
        raise ApiError(409, "conflict", "already subscribed to this feed") from None
    return _shape(sub, feed)


@router.patch("/{sub_id}", response_model=SubscriptionResponse)
async def update_subscription(
    sub_id: int, body: UpdateSubscriptionRequest, user: CurrentUser, session: Session
) -> SubscriptionResponse:
    fields = body.model_fields_set
    if "folder_id" in fields and body.folder_id is not None:
        await _require_own_folder(session, user.id, body.folder_id)

    sub = await subs_store.update(
        session,
        user.id,
        sub_id,
        title_override=body.title_override,
        folder_id=body.folder_id,
        set_title_override="title_override" in fields,
        set_folder_id="folder_id" in fields,
    )
    if sub is None:
        raise ApiError(404, "not_found", "subscription not found")
    feed = await feeds_store.get(session, sub.feed_id)
    assert feed is not None  # FK guarantees the feed exists
    return _shape(sub, feed)


@router.delete("/{sub_id}", status_code=204)
async def delete_subscription(sub_id: int, user: CurrentUser, session: Session) -> None:
    if not await subs_store.delete(session, user.id, sub_id):
        raise ApiError(404, "not_found", "subscription not found")


@router.post("/{sub_id}/refresh", response_model=RefreshResponse, status_code=202)
async def refresh_subscription(sub_id: int, user: CurrentUser, session: Session) -> RefreshResponse:
    sub = await subs_store.get(session, user.id, sub_id)
    if sub is None:
        raise ApiError(404, "not_found", "subscription not found")
    window = get_settings().subscription_refresh_window_s
    if not _refresh_cooldown.allow(sub.feed_id, window):
        raise ApiError(429, "rate_limited", "feed was refreshed too recently")
    await feeds_store.request_immediate_check(session, sub.feed_id)
    return RefreshResponse(status="queued")
