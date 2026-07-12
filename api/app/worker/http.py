"""A generic SSRF-guarded HTTP GET, shared by discovery and favicon fetching.

Like ``fetch_feed`` but general-purpose (no conditional GET / feed semantics):
same SSRF guard on every redirect hop, connect pinned to the validated IP, honest
User-Agent, total timeout, and a hard decoded-size cap aborted mid-stream.
"""

import asyncio
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.config import Settings, get_settings
from app.worker.ssrf import SSRFError, SSRFGuardedTransport, guard_url

_REDIRECTS = frozenset({301, 302, 303, 307, 308})


@dataclass(frozen=True)
class GetResult:
    ok: bool
    status: int | None = None
    content_type: str | None = None
    body: bytes | None = None
    final_url: str | None = None
    error: str | None = None


async def guarded_get(
    url: str,
    *,
    max_bytes: int,
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    accept: str | None = None,
    truncate: bool = False,
) -> GetResult:
    """GET ``url`` safely. Returns ``ok=True`` with body/content_type on a 2xx,
    otherwise ``ok=False`` with a status or error (never raises for network/SSRF).

    With ``truncate=True`` an over-cap response is cut to ``max_bytes`` and still
    returned ``ok=True`` (feed discovery only needs the head to detect the feed);
    otherwise exceeding ``max_bytes`` is an error (the caller wants the whole body)."""
    settings = settings or get_settings()
    allow_hosts = settings.fetch_allow_hosts_set
    owns_transport = transport is None
    transport = transport or SSRFGuardedTransport(allow_hosts=allow_hosts)

    headers = {"User-Agent": settings.user_agent, "Accept-Encoding": "gzip, deflate"}
    if accept:
        headers["Accept"] = accept

    try:
        async with asyncio.timeout(settings.fetch_timeout_s):
            async with httpx.AsyncClient(
                transport=transport,
                headers=headers,
                follow_redirects=False,
                timeout=httpx.Timeout(settings.fetch_timeout_s),
            ) as client:
                for _ in range(settings.fetch_max_redirects + 1):
                    try:
                        await guard_url(url, allow_hosts=allow_hosts)
                    except SSRFError as exc:
                        return GetResult(ok=False, final_url=url, error=str(exc))
                    try:
                        async with client.stream("GET", url) as resp:
                            if resp.status_code in _REDIRECTS:
                                loc = resp.headers.get("location")
                                if not loc:
                                    return GetResult(
                                        ok=False, status=resp.status_code, final_url=str(resp.url)
                                    )
                                url = urljoin(str(resp.url), loc)
                                continue
                            if resp.status_code >= 400 or resp.status_code < 200:
                                return GetResult(
                                    ok=False, status=resp.status_code, final_url=str(resp.url)
                                )
                            chunks = bytearray()
                            async for chunk in resp.aiter_bytes():
                                chunks += chunk
                                if len(chunks) > max_bytes:
                                    if not truncate:
                                        return GetResult(
                                            ok=False,
                                            status=resp.status_code,
                                            final_url=str(resp.url),
                                            error=f"response exceeded {max_bytes} bytes",
                                        )
                                    del chunks[max_bytes:]  # keep the head, stop reading
                                    break
                            return GetResult(
                                ok=True,
                                status=resp.status_code,
                                content_type=resp.headers.get("content-type"),
                                body=bytes(chunks),
                                final_url=str(resp.url),
                            )
                    except httpx.TimeoutException:
                        return GetResult(ok=False, final_url=url, error="timeout")
                    except SSRFError as exc:
                        return GetResult(ok=False, final_url=url, error=str(exc))
                    except httpx.HTTPError as exc:
                        return GetResult(ok=False, final_url=url, error=str(exc))
            return GetResult(ok=False, final_url=url, error="too many redirects")
    except TimeoutError:
        return GetResult(ok=False, final_url=url, error="timeout")
    finally:
        if owns_transport:
            await transport.aclose()
