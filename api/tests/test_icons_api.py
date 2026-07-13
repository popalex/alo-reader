"""Favicon fetching in the worker + GET /icons/{id} serving (WP-08)."""

import httpx
import pytest

from app import db as app_db
from app.models import Feed
from app.store import feeds as feeds_store
from app.store import icons as icons_store
from app.worker.icons import fetch_favicon
from app.worker.pipeline import process_feed
from tests import wutil

from .conftest import PatUser

pytestmark = pytest.mark.usefixtures("public_dns")

PNG = b"\x89PNG\r\n\x1a\nFAKEICONDATA"


def _site_transport(
    icon_path: str = "/favicon-32.png", *, serve_link: bool = True
) -> httpx.MockTransport:
    """Serves a feed at /rss, its site page at /, and a PNG icon."""
    head = f'<link rel="icon" href="{icon_path}">' if serve_link else ""

    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/rss":
            return httpx.Response(200, content=wutil.rss([("g1", "One")]))
        if p == "/":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=f"<html><head>{head}</head></html>".encode(),
            )
        if p in (icon_path, "/favicon.ico"):
            return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def _bare_feed(feed_url: str) -> Feed:
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        feed = await feeds_store.create(s, feed_url=feed_url)
        feed_id = feed.id
    async with sf() as s:
        loaded = await s.get(Feed, feed_id)
        assert loaded is not None
        return loaded


async def test_worker_fetches_and_stores_favicon(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    sf = app_db.get_sessionmaker()
    feed = await _bare_feed("https://feed.example/rss")
    settings = wutil.worker_settings(worker_fetch_favicons=True)

    outcome = await process_feed(sf, feed, settings=settings, transport=_site_transport())
    assert outcome.status == "new_body"

    async with sf() as s:
        refreshed = await s.get(Feed, feed.id)
        assert refreshed is not None and refreshed.icon_id is not None
        icon = await icons_store.get(s, refreshed.icon_id)
        assert icon is not None and icon.data == PNG and icon.mime == "image/png"
        icon_id = refreshed.icon_id

    # Served publicly (no auth header) with long-lived cache headers.
    resp = await api_client.get(f"/api/v1/icons/{icon_id}")
    assert resp.status_code == 200
    assert resp.content == PNG
    assert resp.headers["content-type"].startswith("image/png")
    assert "immutable" in resp.headers["cache-control"]

    # And surfaced on the subscription.
    await api_client.post(
        "/api/v1/subscriptions",
        json={"feed_url": "https://feed.example/rss"},
        headers=pat_user.headers,
    )
    subs = (await api_client.get("/api/v1/subscriptions", headers=pat_user.headers)).json()
    # Content-versioned (?v=<hash>) so a changed icon busts the immutable cache.
    assert subs[0]["icon_url"].startswith(f"/api/v1/icons/{icon_id}?v=")


async def test_favicon_falls_back_to_favicon_ico(api_db: str) -> None:
    # No <link rel=icon> on the page → /favicon.ico is fetched.
    favicon = await fetch_favicon(
        "https://feed.example/",
        settings=wutil.worker_settings(worker_fetch_favicons=True),
        transport=_site_transport(serve_link=False),
    )
    assert favicon is not None and favicon.data == PNG
    assert favicon.url == "https://feed.example/favicon.ico"


async def test_favicon_prefers_feed_image_over_site_favicon(api_db: str) -> None:
    # A feed's own artwork (<image>/<itunes:image>) beats the generic site favicon.
    art = b"\x89PNG\r\n\x1a\nSHOWART"

    def handler(req: httpx.Request) -> httpx.Response:
        # Only the artwork is reachable; the site favicon would 404 — so a passing
        # test proves the artwork was preferred (the site was never needed).
        if req.url.path == "/cover.jpg":
            return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=art)
        return httpx.Response(404)

    favicon = await fetch_favicon(
        "https://feed.example/",
        image_url="https://feed.example/cover.jpg",
        settings=wutil.worker_settings(worker_fetch_favicons=True),
        transport=httpx.MockTransport(handler),
    )
    assert favicon is not None
    assert favicon.data == art  # the feed's artwork, not the /favicon PNG
    assert favicon.mime == "image/jpeg"


async def test_favicon_falls_back_when_feed_image_fails(api_db: str) -> None:
    # Feed image URL 404s → fall back to the site favicon.
    favicon = await fetch_favicon(
        "https://feed.example/",
        image_url="https://feed.example/missing.jpg",
        settings=wutil.worker_settings(worker_fetch_favicons=True),
        transport=_site_transport(),
    )
    assert favicon is not None and favicon.data == PNG  # the site favicon


async def test_missing_icon_is_404(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.get("/api/v1/icons/999999")
    assert resp.status_code == 404


async def test_favicon_disabled_by_default_in_worker_settings(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    feed = await _bare_feed("https://feed.example/rss")
    # wutil default has favicons off, so no icon is fetched even with a serving transport.
    await process_feed(sf, feed, settings=wutil.worker_settings(), transport=_site_transport())
    async with sf() as s:
        refreshed = await s.get(Feed, feed.id)
        assert refreshed is not None and refreshed.icon_id is None
