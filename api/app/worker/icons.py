"""Favicon fetching for a feed's site (DESIGN.md §5, WP-08).

Best-effort and SSRF-guarded: parse the site page for ``<link rel="icon">``, else
fall back to ``/favicon.ico``; fetch the image under a hard size cap. Returns None on
any failure — a missing favicon never affects the poll.
"""

from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx

from app.config import Settings
from app.worker.http import guarded_get


@dataclass(frozen=True)
class Favicon:
    url: str
    mime: str
    data: bytes


class _IconLinkParser(HTMLParser):
    """Collect the first ``<link rel=…icon…>`` href from a page head."""

    def __init__(self) -> None:
        super().__init__()
        self.href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link" or self.href is not None:
            return
        d = {k.lower(): (v or "") for k, v in attrs}
        if "icon" in d.get("rel", "").lower() and d.get("href"):
            self.href = d["href"]


def _icon_href(body: bytes) -> str | None:
    parser = _IconLinkParser()
    parser.feed(body.decode("utf-8", "replace"))
    return parser.href


async def _fetch_image(
    url: str,
    *,
    max_bytes: int,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
) -> Favicon | None:
    """Fetch + validate an image URL (SSRF-guarded, size-capped, image/* only)."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    got = await guarded_get(url, max_bytes=max_bytes, settings=settings, transport=transport)
    if not got.ok or not got.body:
        return None
    mime = (got.content_type or "").split(";")[0].strip()
    if mime and not mime.startswith("image/"):
        return None  # not an image (e.g. an HTML 404 page served as 200)
    return Favicon(url=got.final_url or url, mime=mime or "image/x-icon", data=got.body)


async def fetch_favicon(
    site_url: str | None,
    *,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    image_url: str | None = None,
) -> Favicon | None:
    """Resolve and fetch a feed's icon, or None. Prefers the feed's own artwork
    (``image_url`` from <image>/<itunes:image>) over the site favicon — the favicon is
    usually the generic platform logo. ``transport`` is reused across fetches (tests
    inject a MockTransport)."""
    if image_url:
        icon = await _fetch_image(
            image_url,
            max_bytes=settings.feed_image_max_bytes,
            settings=settings,
            transport=transport,
        )
        if icon is not None:
            return icon  # fall through to the site favicon only if the artwork fails

    if not site_url:
        return None
    parts = urlsplit(site_url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None

    icon_url: str | None = None
    page = await guarded_get(
        site_url, max_bytes=settings.discover_max_bytes, settings=settings, transport=transport
    )
    if page.ok and page.body:
        href = _icon_href(page.body)
        if href:
            icon_url = urljoin(page.final_url or site_url, href)
    if icon_url is None:
        icon_url = f"{parts.scheme}://{parts.netloc}/favicon.ico"

    return await _fetch_image(
        icon_url, max_bytes=settings.favicon_max_bytes, settings=settings, transport=transport
    )
