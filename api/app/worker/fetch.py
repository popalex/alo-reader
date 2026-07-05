"""Polite, SSRF-guarded feed fetcher (DESIGN.md §1.3).

``fetch_feed`` performs one conditional GET for a feed and classifies the outcome
into a :class:`FetchResult`. It is deliberately DB- and schedule-free: the worker
loop (WP-05) owns claiming feeds, persisting bodies, and backoff; parsing is WP-03.

Politeness / safety, all enforced here:

* conditional GET with the feed's stored ``ETag`` / ``Last-Modified`` (most polls
  come back ``304``);
* honest ``User-Agent`` with a contact URL, gzip accepted;
* a single total timeout across the whole redirect chain;
* a hard response-size cap, aborted mid-stream (defends against gzip bombs — the
  cap is on *decoded* bytes);
* redirects followed manually, capped, and **SSRF-revalidated on every hop**;
* permanent redirects surfaced so the caller can repoint ``feed_url``;
* ``429`` ``Retry-After`` surfaced for backoff.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal, Protocol
from urllib.parse import urljoin

import httpx

from app.config import Settings, get_settings
from app.worker.ssrf import SSRFError, SSRFGuardedTransport, guard_url

FetchStatus = Literal["not_modified", "new_body", "http_error", "network_error", "blocked"]

# Statuses treated as a permanent move (caller should update feed_url).
_PERMANENT_REDIRECTS = frozenset({301, 308})
_REDIRECTS = frozenset({301, 302, 303, 307, 308})


class FetchTarget(Protocol):
    """What the fetcher needs from a feed row (see ``app.models.Feed``)."""

    feed_url: str
    etag: str | None
    last_modified: str | None


@dataclass(frozen=True)
class FetchResult:
    status: FetchStatus
    final_url: str
    body: bytes | None = None
    etag: str | None = None
    last_modified: str | None = None
    http_status: int | None = None
    retry_after: float | None = None
    # Set only when the feed moved permanently; the value is the new feed_url.
    permanent_url: str | None = None
    error: str | None = None


def _parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse a ``Retry-After`` header (delta-seconds or HTTP-date) to seconds."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    return max(0.0, (when - now).total_seconds())


def _conditional_headers(target: FetchTarget) -> dict[str, str]:
    headers: dict[str, str] = {}
    if target.etag:
        headers["If-None-Match"] = target.etag
    if target.last_modified:
        headers["If-Modified-Since"] = target.last_modified
    return headers


async def fetch_feed(
    target: FetchTarget,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    settings: Settings | None = None,
) -> FetchResult:
    """Fetch ``target.feed_url`` once and classify the result.

    ``transport`` lets tests inject an ``httpx.MockTransport``; in production a
    fresh :class:`SSRFGuardedTransport` is created and closed per call.
    """
    settings = settings or get_settings()
    allow_hosts = settings.fetch_allow_hosts_set
    owns_transport = transport is None
    transport = transport or SSRFGuardedTransport(allow_hosts=allow_hosts)

    base_headers = {
        "User-Agent": settings.user_agent,
        "Accept-Encoding": "gzip, deflate",
    }
    url = target.feed_url
    redirected = False
    all_permanent = True

    try:
        async with asyncio.timeout(settings.fetch_timeout_s):
            async with httpx.AsyncClient(
                transport=transport,
                headers=base_headers,
                follow_redirects=False,
                timeout=httpx.Timeout(settings.fetch_timeout_s),
            ) as client:
                for hop in range(settings.fetch_max_redirects + 1):
                    try:
                        await guard_url(url, allow_hosts=allow_hosts)
                    except SSRFError as exc:
                        return FetchResult("blocked", final_url=url, error=str(exc))

                    # Conditional headers only make sense on the first request.
                    headers = _conditional_headers(target) if hop == 0 else {}
                    try:
                        async with client.stream("GET", url, headers=headers) as resp:
                            if resp.status_code in _REDIRECTS:
                                location = resp.headers.get("location")
                                if not location:
                                    return FetchResult(
                                        "http_error",
                                        final_url=str(resp.url),
                                        http_status=resp.status_code,
                                        error="redirect without Location",
                                    )
                                redirected = True
                                if resp.status_code not in _PERMANENT_REDIRECTS:
                                    all_permanent = False
                                url = urljoin(str(resp.url), location)
                                continue

                            return await _classify_final(
                                resp,
                                redirected=redirected,
                                all_permanent=all_permanent,
                                max_bytes=settings.fetch_max_bytes,
                            )
                    except httpx.TimeoutException:
                        return FetchResult("network_error", final_url=url, error="timeout")
                    except SSRFError as exc:
                        # Raised by the guarded backend on a rebind at connect time.
                        return FetchResult("blocked", final_url=url, error=str(exc))
                    except httpx.HTTPError as exc:
                        return FetchResult("network_error", final_url=url, error=str(exc))

            return FetchResult(
                "network_error",
                final_url=url,
                error=f"exceeded {settings.fetch_max_redirects} redirects",
            )
    except TimeoutError:
        return FetchResult("network_error", final_url=url, error="timeout")
    finally:
        if owns_transport:
            await transport.aclose()


async def _classify_final(
    resp: httpx.Response, *, redirected: bool, all_permanent: bool, max_bytes: int
) -> FetchResult:
    final_url = str(resp.url)
    # Only a clean permanent-redirect chain justifies repointing feed_url.
    permanent_url = final_url if redirected and all_permanent else None

    if resp.status_code == 304:
        return FetchResult(
            "not_modified",
            final_url=final_url,
            etag=resp.request.headers.get("if-none-match"),
            permanent_url=permanent_url,
        )

    if resp.status_code == 429:
        return FetchResult(
            "http_error",
            final_url=final_url,
            http_status=429,
            retry_after=_parse_retry_after(resp.headers.get("retry-after")),
            permanent_url=permanent_url,
        )

    if resp.status_code >= 400 or resp.status_code < 200:
        return FetchResult(
            "http_error",
            final_url=final_url,
            http_status=resp.status_code,
            permanent_url=permanent_url,
        )

    # 2xx: stream the body, aborting the moment the decoded size exceeds the cap.
    chunks = bytearray()
    async for chunk in resp.aiter_bytes():
        chunks += chunk
        if len(chunks) > max_bytes:
            return FetchResult(
                "network_error",
                final_url=final_url,
                http_status=resp.status_code,
                error=f"response exceeded {max_bytes} bytes",
            )

    return FetchResult(
        "new_body",
        final_url=final_url,
        body=bytes(chunks),
        etag=resp.headers.get("etag"),
        last_modified=resp.headers.get("last-modified"),
        http_status=resp.status_code,
        permanent_url=permanent_url,
    )
