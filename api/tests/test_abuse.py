"""Abuse-scenario suite (WP-15 acceptance, DESIGN.md §2 risks 3–7).

The adversarial end-to-end checks the operator re-runs before a release:

* the SSRF probe set driven **through the full API path** — /discover (page fetch)
  and /subscriptions → the worker poll (feed fetch) — not just the guard's unit tests;
* a deleted user's PAT can no longer authenticate (webhook cascade closes the door);
* quota bypass attempts are refused.

SSRF probes use IP *literals* so the guard rejects them before any socket opens —
no real network, no mock resolver needed.
"""

from collections.abc import Callable, Iterator

import httpx
import pytest
from sqlalchemy import update

from app import db as app_db
from app.auth import pat
from app.config import get_settings
from app.models import User
from app.store import users as users_store
from app.worker.main import Counters, poll_once
from tests import wutil

from .conftest import PatUser, make_pat_user

DISCOVER = "/api/v1/discover"
SUBS = "/api/v1/subscriptions"

# Blocked-range literals (mirrors test_ssrf's classes): loopback, private, cloud
# metadata, IPv6 loopback, CGNAT.
SSRF_PROBES = [
    "http://127.0.0.1/feed",
    "http://10.0.0.5/feed",
    "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
    "http://[::1]/feed",
    "http://100.64.0.1/feed",
]


@pytest.fixture
def no_discover_cooldown(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Disable the per-user discover spacing so the probe loop isn't 429'd."""
    monkeypatch.setenv("DISCOVER_WINDOW_S", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_ssrf_probes_blocked_via_discover(
    api_client: httpx.AsyncClient, pat_user: PatUser, no_discover_cooldown: None
) -> None:
    # The real guarded fetch runs (not stubbed): each internal target is refused,
    # so discovery yields nothing and never reaches the address.
    for url in SSRF_PROBES:
        resp = await api_client.post(DISCOVER, json={"url": url}, headers=pat_user.headers)
        assert resp.status_code == 200, url
        assert resp.json() == [], url


async def test_ssrf_blocked_via_subscribe_then_poll(api_client: httpx.AsyncClient) -> None:
    # Subscribing to an internal URL is allowed at the API (it's just a row), but the
    # worker's fetch is SSRF-guarded, so no content is ever ingested from it.
    sf = app_db.get_sessionmaker()
    pat_u = await make_pat_user("ssrf-sub@example.com")
    resp = await api_client.post(
        SUBS, json={"feed_url": "http://10.0.0.1/rss"}, headers=pat_u.headers
    )
    assert resp.status_code == 201
    feed_id = resp.json()["feed_id"]

    # Real fetch_feed + real SSRF transport; no public_dns fixture, so the literal
    # private IP is validated and rejected before a socket opens.
    settings = wutil.worker_settings()
    counters = Counters()
    await poll_once(sf, settings=settings, counters=counters)

    assert await wutil.count_entries(sf, feed_id) == 0
    feed = await wutil.get_feed(sf, feed_id)
    assert feed.last_error is not None
    assert feed.error_count == 1


async def test_deleted_user_pat_reuse_rejected(
    api_client: httpx.AsyncClient, pat_user: PatUser, set_auth_mode: Callable[[str], None]
) -> None:
    # Clerk mode: an anonymous request is NOT mapped to a local user (none-mode would),
    # so a revoked identity truly fails closed.
    set_auth_mode("clerk")
    assert (await api_client.get("/api/v1/me", headers=pat_user.headers)).status_code == 200

    async with app_db.get_sessionmaker()() as s, s.begin():
        assert await users_store.delete(s, pat_user.user_id)  # webhook user.deleted cascade

    reused = await api_client.get("/api/v1/me", headers=pat_user.headers)
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "unauthenticated"


async def _set_quota(user_id: int, quota: int) -> None:
    async with app_db.get_sessionmaker()() as s, s.begin():
        await s.execute(update(User).where(User.id == user_id).values(quota_subs=quota))


async def test_subscription_quota_bypass_fails(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    await _set_quota(pat_user.user_id, 1)
    first = await api_client.post(
        SUBS, json={"feed_url": "https://a.example/rss"}, headers=pat_user.headers
    )
    assert first.status_code == 201

    # Direct POST over the cap is refused...
    over = await api_client.post(
        SUBS, json={"feed_url": "https://b.example/rss"}, headers=pat_user.headers
    )
    assert over.status_code == 422
    assert over.json()["error"]["code"] == "quota_exceeded"

    # ...and so is the OPML import path (can't launder extra subs past the quota).
    opml = (
        b'<?xml version="1.0"?><opml version="2.0"><body>'
        b'<outline type="rss" xmlUrl="https://c.example/rss"/>'
        b'<outline type="rss" xmlUrl="https://d.example/rss"/>'
        b"</body></opml>"
    )
    report = await api_client.post(
        "/api/v1/opml",
        files={"file": ("subs.opml", opml, "text/x-opml")},
        headers=pat_user.headers,
    )
    assert report.status_code == 200
    body = report.json()
    assert body["imported"] == 0
    assert any(f["reason"] == "quota exceeded" for f in body["failed"])

    # The database really is at the cap, not merely reporting so.
    async with app_db.get_sessionmaker()() as s:
        from app.store import subscriptions as subs_store

        assert await subs_store.count_for_user(s, pat_user.user_id) == 1


async def test_api_token_quota_bypass_fails(
    api_client: httpx.AsyncClient, pat_user: PatUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QUOTA_API_TOKENS", "1")
    get_settings.cache_clear()
    try:
        # The fixture user already holds one PAT, so the next mint is over the cap.
        resp = await api_client.post(
            "/api/v1/tokens", json={"label": "extra"}, headers=pat_user.headers
        )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "quota_exceeded"
        async with app_db.get_sessionmaker()() as s:
            assert await pat.count_for_user(s, pat_user.user_id) == 1
    finally:
        get_settings.cache_clear()
