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
from urllib.parse import urlsplit

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


# Body preference, best first. Anything unlisted ranks 0, so a feed that offers only
# an unusual type still yields its single content element.
_CONTENT_TYPE_RANK = {
    "text/html": 3,
    "application/xhtml+xml": 2,
    "text/plain": 1,
}


def _to_utc(parsed: time.struct_time | None) -> datetime | None:
    """A feedparser ``*_parsed`` struct_time (already UTC) → aware UTC datetime."""
    if parsed is None:
        return None
    try:
        return datetime.fromtimestamp(time.mktime(parsed) - time.timezone, tz=UTC)
    except ValueError, OverflowError, OSError:
        return None


def _safe_url(value: object) -> str | None:
    """A feed-supplied URL, or None unless it is http(s).

    feedparser hands these through untouched, so an entry <link> can be
    ``javascript:alert(document.cookie)`` or a ``data:text/html`` document. The SPA
    renders it as an href, and React only refuses javascript: URLs in development
    builds, so this is the one place it can be stopped. The content sanitizer applies
    the same allowlist to hrefs inside the body.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    url = value.strip()
    scheme = urlsplit(url).scheme.lower()
    if scheme in ("http", "https"):
        return url
    # A protocol-relative or relative URL carries no scheme of its own; it inherits
    # the page's, which is https for the SPA, so it cannot smuggle javascript:.
    return url if scheme == "" else None


def _raw_get(entry: dict[str, Any], key: str) -> Any:
    """Read a key without feedparser's deprecated updated → published fallback.

    feedparser maps a missing ``updated_parsed`` onto ``published_parsed`` and warns
    about it. That would make the fallback below re-read the very timestamp it is
    trying to get away from, so ask the plain dict instead.
    """
    return dict.get(entry, key)


def _published_at(entry: dict[str, Any], now: datetime) -> datetime | None:
    """First usable timestamp, preferring published over updated.

    The future check runs per candidate: an entry dated 2099 used to short-circuit
    the `or`, so a perfectly good `updated` was never consulted and the entry landed
    with no date at all — which sorts it to the bottom and makes it the first thing
    dropped when a feed exceeds WORKER_MAX_ENTRIES_PER_FETCH.
    """
    for key in ("published_parsed", "updated_parsed"):
        dt = _to_utc(_raw_get(entry, key))
        if dt is not None and dt <= now + _MAX_FUTURE:
            return dt
    return None


def _content_html(entry: dict[str, Any]) -> str:
    """Best available body: Atom ``content`` first, else ``summary``/description."""
    contents = entry.get("content")
    if contents:
        # feedparser gives a list of {'value', 'type', ...}. Rank the types rather
        # than testing for one: `max` over a boolean key returns the *first* element
        # when nothing matches, and feedparser normalizes Atom type="xhtml" to
        # application/xhtml+xml, which never equalled "text/html". An entry carrying
        # a text teaser before its xhtml body therefore stored the teaser and threw
        # the article away.
        best = max(contents, key=lambda c: _CONTENT_TYPE_RANK.get(c.get("type", ""), 0))
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
        # Synthetic: stable across re-fetches of the same entry, and distinct between
        # entries. Title and date alone collide whenever a feed ships several
        # untitled, undated items — and insert_batch's ON CONFLICT DO NOTHING then
        # drops all but the first, permanently, because the hash repeats on every
        # later fetch. The body is what tells them apart.
        stamp = published_at.isoformat() if published_at else ""
        body = _content_html(entry)
        basis, source = f"{title}\x00{stamp}\x00{body}", "synthetic"
    return hashlib.sha256(basis.encode("utf-8")).digest(), source


def _normalize_entry(entry: dict[str, Any], now: datetime) -> ParsedEntry:
    title = title_to_text(entry.get("title", ""))
    published_at = _published_at(entry, now)
    guid_hash, guid_source = _guid(entry, title, published_at)
    author = entry.get("author") or None
    url = _safe_url(entry.get("link"))
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
        site_url=_safe_url(feed.get("link")),
        version=d.get("version", "") or "",
        bozo=bool(d.get("bozo", False)),
        encoding=d.get("encoding") or None,
        image_url=_safe_url((feed.get("image") or {}).get("href")),
        entries=[_normalize_entry(e, now) for e in d.get("entries", [])],
    )
