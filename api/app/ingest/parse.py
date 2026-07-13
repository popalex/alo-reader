"""feedparser wrapper: raw feed bytes → normalized dataclasses.

Pure and I/O-free (feedparser does no network here — it parses the bytes we hand
it). The messy real-world feed (RSS 0.9x/1.0/2.0, Atom, malformed XML, wrong
declared encodings) is normalized into :class:`ParsedFeed` / :class:`ParsedEntry`
with a deterministic GUID chain and UTC-normalized dates.

Content HTML is returned *raw* here; sanitization is a separate stage
(:mod:`app.ingest.sanitize`) per the DESIGN.md §1.3 pipeline (parse → sanitize).
"""

import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import feedparser  # type: ignore[import-untyped]

from app.ingest.sanitize import MAX_RAW_CONTENT_CHARS, title_to_text

# A date claimed to be more than this far ahead is treated as unknown, not honored
# (feeds routinely emit garbage/typo'd future dates; DESIGN normalization rule).
_MAX_FUTURE = timedelta(hours=48)

GuidSource = Literal["guid", "link", "synthetic"]


@dataclass(frozen=True)
class ParsedEntry:
    guid_hash: bytes
    guid_source: GuidSource
    url: str | None
    title: str
    author: str | None
    content_html: str
    published_at: datetime | None


@dataclass(frozen=True)
class ParsedFeed:
    title: str
    site_url: str | None
    version: str
    bozo: bool
    encoding: str | None
    # The feed's own artwork (<image><url> / <itunes:image>), preferred over the site
    # favicon as the feed icon — the favicon is usually the generic platform logo.
    image_url: str | None = None
    entries: list[ParsedEntry] = field(default_factory=list)


def _to_utc(parsed: time.struct_time | None) -> datetime | None:
    """A feedparser ``*_parsed`` struct_time (already UTC) → aware UTC datetime."""
    if parsed is None:
        return None
    try:
        return datetime.fromtimestamp(time.mktime(parsed) - time.timezone, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _published_at(entry: dict[str, Any], now: datetime) -> datetime | None:
    dt = _to_utc(entry.get("published_parsed")) or _to_utc(entry.get("updated_parsed"))
    if dt is None:
        return None
    if dt > now + _MAX_FUTURE:
        return None
    return dt


def _content_html(entry: dict[str, Any]) -> str:
    """Best available body: Atom ``content`` first, else ``summary``/description."""
    contents = entry.get("content")
    if contents:
        # feedparser gives a list of {'value', 'type', ...}; prefer text/html.
        best = max(contents, key=lambda c: c.get("type") == "text/html")
        value = best.get("value", "")
    else:
        value = entry.get("summary", "")
    value = value or ""
    if len(value) > MAX_RAW_CONTENT_CHARS:
        value = value[:MAX_RAW_CONTENT_CHARS]
    return value


def _guid(
    entry: dict[str, Any], title: str, published_at: datetime | None
) -> tuple[bytes, GuidSource]:
    """Deterministic, always-non-empty dedup key: guid → link → hash(title+date)."""
    source: GuidSource
    guid = entry.get("id")
    link = entry.get("link")
    if guid:
        basis, source = guid, "guid"
    elif link:
        basis, source = link, "link"
    else:
        # Synthetic: stable across re-fetches of the same entry.
        stamp = published_at.isoformat() if published_at else ""
        basis, source = f"{title}\x00{stamp}", "synthetic"
    return hashlib.sha256(basis.encode("utf-8")).digest(), source


def _normalize_entry(entry: dict[str, Any], now: datetime) -> ParsedEntry:
    title = title_to_text(entry.get("title", ""))
    published_at = _published_at(entry, now)
    guid_hash, guid_source = _guid(entry, title, published_at)
    author = entry.get("author") or None
    url = entry.get("link") or None
    return ParsedEntry(
        guid_hash=guid_hash,
        guid_source=guid_source,
        url=url,
        title=title,
        author=author,
        content_html=_content_html(entry),
        published_at=published_at,
    )


def parse_feed(raw: bytes, *, now: datetime | None = None) -> ParsedFeed:
    """Parse raw feed bytes into a normalized :class:`ParsedFeed`.

    ``now`` (default: current UTC time) anchors the future-date rejection window;
    pass it explicitly for deterministic tests.
    """
    now = now or datetime.now(UTC)
    d = feedparser.parse(raw)
    feed = d.get("feed", {})
    return ParsedFeed(
        title=title_to_text(feed.get("title", "")),
        site_url=feed.get("link") or None,
        version=d.get("version", "") or "",
        bozo=bool(d.get("bozo", False)),
        encoding=d.get("encoding") or None,
        image_url=(feed.get("image") or {}).get("href") or None,
        entries=[_normalize_entry(e, now) for e in d.get("entries", [])],
    )
