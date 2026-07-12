"""Feed discovery (DESIGN.md §5): given a page URL, find its feeds.

SSRF-guarded fetch of the page, then parse ``<link rel="alternate" type=…rss/atom…>``
declarations (stdlib ``html.parser`` — no bs4/lxml dependency). If the URL is itself
a feed it's returned directly; if the page declares none, common fallback paths are
offered as candidates (unverified — the subscribe path validates on first poll).
"""

from html.parser import HTMLParser
from typing import Annotated
from urllib.parse import urljoin, urlsplit

import feedparser  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.provider import AuthedUser
from app.auth.ratelimit import Cooldown
from app.auth.runtime import current_user
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.worker.http import guarded_get

router = APIRouter(tags=["discover"])

CurrentUser = Annotated[AuthedUser, Depends(current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]

_FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json")
_FALLBACK_PATHS = ("/feed", "/rss", "/atom.xml", "/index.xml")

# Per-user cooldown: discovery makes the server fetch an arbitrary page, so it's
# gated tighter than the coarse global bucket (DESIGN.md §1.4 quota audit).
_discover_cooldown = Cooldown()


class DiscoverRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class DiscoverCandidate(BaseModel):
    feed_url: str
    title: str


class _LinkParser(HTMLParser):
    """Collect feed <link> declarations and the page <title>."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []  # (href, title)
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "link":
            d = {k.lower(): (v or "") for k, v in attrs}
            rel = d.get("rel", "").lower()
            type_ = d.get("type", "").lower()
            href = d.get("href", "")
            if href and "alternate" in rel and any(t in type_ for t in _FEED_TYPES):
                self.links.append((href, d.get("title", "")))
        elif tag == "title" and not self.title:
            self._in_title = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False


def _discover(body: bytes, base_url: str) -> list[DiscoverCandidate]:
    # The URL might already be a feed — return it directly.
    parsed_feed = feedparser.parse(body)
    if parsed_feed.version:
        title = parsed_feed.feed.get("title") or base_url
        return [DiscoverCandidate(feed_url=base_url, title=title)]

    parser = _LinkParser()
    parser.feed(body.decode("utf-8", "replace"))
    page_title = " ".join(parser.title.split())

    candidates: list[DiscoverCandidate] = []
    seen: set[str] = set()
    for href, link_title in parser.links:
        feed_url = urljoin(base_url, href)
        if feed_url in seen:
            continue
        seen.add(feed_url)
        candidates.append(DiscoverCandidate(feed_url=feed_url, title=link_title or page_title))

    if not candidates:  # no declarations → offer conventional fallback paths
        parts = urlsplit(base_url)
        origin = f"{parts.scheme}://{parts.netloc}"
        for path in _FALLBACK_PATHS:
            candidates.append(
                DiscoverCandidate(feed_url=origin + path, title=page_title or path.lstrip("/"))
            )
    return candidates


@router.post("/discover", response_model=list[DiscoverCandidate])
async def discover(
    body: DiscoverRequest, user: CurrentUser, session: Session
) -> list[DiscoverCandidate]:
    parts = urlsplit(body.url.strip())
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ApiError(400, "invalid_request", "url must be an absolute http(s) URL")

    settings = get_settings()
    if not _discover_cooldown.allow(user.id, settings.discover_window_s):
        raise ApiError(429, "rate_limited", "discovery was requested too recently")
    result = await guarded_get(
        body.url.strip(),
        max_bytes=settings.discover_max_bytes,
        settings=settings,
        accept="text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        # A big feed (podcast feeds run into megabytes) must still be *detected*: we
        # only need the head to read <rss>/<feed> and the channel title, so truncate
        # rather than bailing out — otherwise a valid feed reads as "nothing found".
        truncate=True,
    )
    if not result.ok or result.body is None:
        return []  # unreachable/blocked page → nothing to discover
    return _discover(result.body, result.final_url or body.url.strip())
