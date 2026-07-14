"""Per-feed pipeline: fetch → parse → sanitize → dedup → persist (DESIGN.md §1.3).

``process_feed`` runs the full chain for a single claimed feed inside its own DB
transaction and records the outcome (new entries + rescheduling, or backoff on
error). The CPU-bound parse/sanitize/compress step runs in a worker thread so it
never stalls the event loop. ``fetch`` and ``transport`` are injectable so tests
can drive the whole pipeline with an ``httpx.MockTransport`` and no real network.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.ingest import compress_text, parse_feed, sanitize_and_cap, summarize
from app.ingest.parse import ParsedFeed
from app.store import entries as entries_store
from app.store import feeds as feeds_store
from app.store import icons as icons_store
from app.store import metrics as metrics_store
from app.store.entries import NewEntry
from app.worker.fetch import FetchResult, FetchTarget, fetch_feed
from app.worker.icons import fetch_favicon
from app.worker.schedule import adaptive_interval, error_delay

log = logging.getLogger("worker")

FetchFn = Callable[..., Awaitable[FetchResult]]


class FeedRow(FetchTarget, Protocol):
    """The subset of ``app.models.Feed`` the pipeline reads (all detached-safe)."""

    id: int
    title: str
    site_url: str | None
    check_interval_s: int
    error_count: int
    icon_id: int | None


# Outcome status: new_body | not_modified | http_error | network_error | blocked
# | redirect_conflict (permanent-redirect target already exists).
@dataclass(frozen=True)
class FeedOutcome:
    feed_id: int
    status: str
    new_entries: int = 0
    error: str | None = None


# Sort sentinel for undated entries: they sink below any dated entry, so they're the
# first dropped when a fetch exceeds the per-fetch cap.
_OLDEST = datetime.min.replace(tzinfo=UTC)


def _build_entries(body: bytes, *, max_entries: int) -> tuple[ParsedFeed, list[NewEntry]]:
    """Parse + sanitize a feed body into insertable rows. Pure/CPU — run in a thread."""
    parsed = parse_feed(body)
    entries = parsed.entries
    if len(entries) > max_entries:
        # Only a pathological feed trips this; keep the newest N by publish date so one
        # fetch can't build an unbounded transaction. Normal feeds are untouched.
        entries = sorted(entries, key=lambda e: e.published_at or _OLDEST, reverse=True)[
            :max_entries
        ]
    rows: list[NewEntry] = []
    for e in entries:
        content_html, truncated = sanitize_and_cap(e.content_html)
        rows.append(
            NewEntry(
                guid_hash=e.guid_hash,
                url=e.url,
                title=e.title,
                author=e.author,
                content_html=content_html,
                content_raw=compress_text(e.content_html) if e.content_html else None,
                content_truncated=truncated,
                # Derived here in the worker thread (CPU-bound) so the read path serves
                # a stored preview instead of re-stripping HTML on every listing.
                summary=summarize(content_html),
                published_at=e.published_at,
            )
        )
    return parsed, rows


async def _apply_new_body(
    session: AsyncSession,
    feed: FeedRow,
    result: FetchResult,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
) -> FeedOutcome:
    if result.body is None:  # defensive: new_body always carries a body
        return await _apply_error(session, feed, result, settings, "empty body")
    parsed, rows = await asyncio.to_thread(
        _build_entries, result.body, max_entries=settings.worker_max_entries_per_fetch
    )
    # A 200 that feedparser can't recognize as a feed (empty ``version``) and that
    # yields no items is almost always an HTML page — a wrong or removed feed URL.
    # Record it as an error so the UI shows a failing feed with a message, instead
    # of a silent, untitled, article-less one that looks broken for no reason.
    if not rows and not parsed.version:
        return await _apply_error(
            session, feed, result, settings, "response is not a valid feed", status="not_a_feed"
        )
    inserted = await entries_store.insert_batch(session, feed.id, rows)
    count = len(inserted)
    interval = adaptive_interval(
        feed.check_interval_s,
        count > 0,
        floor_s=settings.worker_interval_floor_s,
        ceil_s=settings.worker_interval_ceil_s,
    )
    site_url = parsed.site_url or feed.site_url
    await feeds_store.record_success(
        session,
        feed.id,
        interval_s=interval,
        etag=result.etag,
        last_modified=result.last_modified,
        title=parsed.title or feed.title,
        site_url=site_url,
    )
    if settings.worker_fetch_favicons and feed.icon_id is None:
        await _maybe_fetch_favicon(
            session, feed.id, site_url, settings, transport, image_url=parsed.image_url
        )
    return FeedOutcome(feed.id, "new_body", new_entries=count)


async def _maybe_fetch_favicon(
    session: AsyncSession,
    feed_id: int,
    site_url: str | None,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
    *,
    image_url: str | None = None,
) -> None:
    """Best-effort: a missing/broken favicon must never fail the poll."""
    try:
        favicon = await fetch_favicon(
            site_url, settings=settings, transport=transport, image_url=image_url
        )
        if favicon is not None:
            icon = await icons_store.get_or_create(
                session, url=favicon.url, mime=favicon.mime, data=favicon.data
            )
            await icons_store.set_feed_icon(session, feed_id, icon.id)
    except Exception as exc:  # noqa: BLE001 — best-effort, log and move on
        log.warning("favicon_fetch_failed feed_id=%s error=%r", feed_id, exc)


async def _apply_not_modified(
    session: AsyncSession, feed: FeedRow, settings: Settings
) -> FeedOutcome:
    interval = adaptive_interval(
        feed.check_interval_s,
        False,
        floor_s=settings.worker_interval_floor_s,
        ceil_s=settings.worker_interval_ceil_s,
    )
    await feeds_store.record_not_modified(session, feed.id, interval_s=interval)
    return FeedOutcome(feed.id, "not_modified")


async def _apply_error(
    session: AsyncSession,
    feed: FeedRow,
    result: FetchResult,
    settings: Settings,
    message: str,
    *,
    status: str | None = None,
) -> FeedOutcome:
    delay = error_delay(
        feed.error_count + 1,
        result.retry_after,
        base_s=settings.worker_backoff_base_s,
        cap_s=settings.worker_backoff_cap_s,
    )
    await feeds_store.record_error(session, feed.id, delay_s=delay, message=message)
    return FeedOutcome(feed.id, status or result.status, error=message)


async def process_feed(
    session_factory: async_sessionmaker[AsyncSession],
    feed: FeedRow,
    *,
    settings: Settings,
    fetch: FetchFn = fetch_feed,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FeedOutcome:
    """Fetch and persist one feed, returning what happened."""
    result = await fetch(feed, transport=transport, settings=settings)
    outcome = await _persist(session_factory, feed, result, settings=settings, transport=transport)
    # Metrics are recorded in their own short transaction, decoupled from the ingest
    # commit above: a hot-row contention or failure on the shared counter rows must
    # never roll back the entries we just stored, and the counter lock is held only
    # for this tiny write rather than across the whole parse/insert transaction.
    await _record(session_factory, feed, result, outcome)
    return outcome


async def _persist(
    session_factory: async_sessionmaker[AsyncSession],
    feed: FeedRow,
    result: FetchResult,
    *,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None,
) -> FeedOutcome:
    """Persist the fetch outcome (entries + rescheduling, or backoff) in one tx."""
    async with session_factory() as session, session.begin():
        # A clean permanent redirect repoints feed_url before anything else; a
        # unique collision is surfaced as an error, never a silent feed merge.
        if result.permanent_url and result.permanent_url != feed.feed_url:
            if not await feeds_store.update_feed_url(session, feed.id, result.permanent_url):
                return await _apply_error(
                    session,
                    feed,
                    result,
                    settings,
                    "permanent redirect target already exists",
                    status="redirect_conflict",
                )

        if result.status == "new_body":
            return await _apply_new_body(session, feed, result, settings, transport)
        if result.status == "not_modified":
            return await _apply_not_modified(session, feed, settings)
        # http_error / network_error / blocked
        message = result.error or f"HTTP {result.http_status}"
        return await _apply_error(session, feed, result, settings, message)


async def _record(
    session_factory: async_sessionmaker[AsyncSession],
    feed: FeedRow,
    result: FetchResult,
    outcome: FeedOutcome,
) -> None:
    """Record the fetch outcome + per-host 4xx into the /metrics counters (WP-15).

    Best-effort and isolated: runs in its own transaction so it can't roll back the
    ingested entries, and swallows failures (a metrics blip must not fail a feed)."""
    host = urlsplit(feed.feed_url).hostname or ""
    try:
        async with session_factory() as session, session.begin():
            await metrics_store.record_fetch(
                session, host=host, outcome=outcome.status, http_status=result.http_status
            )
    except Exception as exc:  # noqa: BLE001 — metrics are non-critical telemetry
        log.warning("metrics_record_failed feed_id=%s error=%r", feed.id, exc)
