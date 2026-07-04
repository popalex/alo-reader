"""Fetcher tests (DESIGN.md §1.3): conditional GET, redirects, caps, SSRF.

HTTP is driven by ``httpx.MockTransport`` and DNS by a mock resolver, so no real
network or sockets are touched. The oversize test is guarded by a loop-watchdog
fixture asserting the event loop is never blocked >100 ms.
"""

import asyncio
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from app.config import Settings
from app.worker import ssrf
from app.worker.fetch import FetchResult, fetch_feed


class _Target:
    def __init__(self, feed_url: str, etag: str | None = None, last_modified: str | None = None):
        self.feed_url = feed_url
        self.etag = etag
        self.last_modified = last_modified


def _settings(**over: object) -> Settings:
    base: dict[str, object] = {"database_url": "postgresql+asyncpg://x/y", "auth_mode": "none"}
    base.update(over)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """All hostnames resolve to a public IP, except ``internal.*`` → private."""

    async def fake(host: str, port: int) -> list[str]:
        if host.startswith("internal."):
            return ["10.0.0.7"]
        return ["93.184.216.34"]

    monkeypatch.setattr(ssrf, "resolve", fake)


def _mock(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


async def _run(
    url: str, handler: Callable[[httpx.Request], httpx.Response], **over: object
) -> FetchResult:
    return await fetch_feed(_Target(url), transport=_mock(handler), settings=_settings(**over))


# ── Happy paths / classification ─────────────────────────────────────────────


async def test_200_new_body(public_dns: None) -> None:
    def h(req: httpx.Request) -> httpx.Response:
        assert req.headers["user-agent"].startswith("alo-reader/")
        return httpx.Response(
            200,
            headers={"ETag": '"v1"', "Last-Modified": "Wed, 02 Jul 2025 00:00:00 GMT"},
            content=b"<rss>hello</rss>",
        )

    r = await _run("https://feed.example/rss", h)
    assert r.status == "new_body"
    assert r.body == b"<rss>hello</rss>"
    assert r.etag == '"v1"'
    assert r.last_modified == "Wed, 02 Jul 2025 00:00:00 GMT"
    assert r.permanent_url is None


async def test_conditional_headers_sent(public_dns: None) -> None:
    seen: dict[str, str] = {}

    def h(req: httpx.Request) -> httpx.Response:
        seen.update(req.headers)
        return httpx.Response(304)

    r = await fetch_feed(
        _Target(
            "https://feed.example/rss", etag='"v1"', last_modified="Wed, 02 Jul 2025 00:00:00 GMT"
        ),
        transport=_mock(h),
        settings=_settings(),
    )
    assert r.status == "not_modified"
    assert seen["if-none-match"] == '"v1"'
    assert seen["if-modified-since"] == "Wed, 02 Jul 2025 00:00:00 GMT"


async def test_429_retry_after_seconds(public_dns: None) -> None:
    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "120"})

    r = await _run("https://feed.example/rss", h)
    assert r.status == "http_error"
    assert r.http_status == 429
    assert r.retry_after == 120.0


async def test_http_error_4xx(public_dns: None) -> None:
    r = await _run("https://feed.example/rss", lambda req: httpx.Response(404))
    assert r.status == "http_error"
    assert r.http_status == 404


# ── Redirects ────────────────────────────────────────────────────────────────


async def test_permanent_redirect_surfaced(public_dns: None) -> None:
    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/old":
            return httpx.Response(301, headers={"Location": "https://feed.example/new"})
        return httpx.Response(200, content=b"<rss/>")

    r = await _run("https://feed.example/old", h)
    assert r.status == "new_body"
    assert r.final_url == "https://feed.example/new"
    assert r.permanent_url == "https://feed.example/new"


async def test_temporary_redirect_not_surfaced_as_permanent(public_dns: None) -> None:
    def h(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/tmp":
            return httpx.Response(302, headers={"Location": "https://feed.example/here"})
        return httpx.Response(200, content=b"<rss/>")

    r = await _run("https://feed.example/tmp", h)
    assert r.status == "new_body"
    assert r.permanent_url is None


async def test_redirect_to_private_ip_is_blocked(public_dns: None) -> None:
    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"Location": "https://internal.example/secret"})

    r = await _run("https://feed.example/old", h)
    assert r.status == "blocked"
    assert "internal.example" in (r.error or "")


async def test_too_many_redirects(public_dns: None) -> None:
    def h(req: httpx.Request) -> httpx.Response:
        n = int(req.url.path.strip("/") or "0")
        return httpx.Response(302, headers={"Location": f"https://feed.example/{n + 1}"})

    r = await _run("https://feed.example/0", h, fetch_max_redirects=3)
    assert r.status == "network_error"
    assert "redirect" in (r.error or "")


# ── SSRF at the top level ────────────────────────────────────────────────────


async def test_blocked_scheme(public_dns: None) -> None:
    r = await _run("ftp://feed.example/rss", lambda req: httpx.Response(200))
    assert r.status == "blocked"


async def test_blocked_private_host(public_dns: None) -> None:
    r = await _run("https://internal.example/rss", lambda req: httpx.Response(200))
    assert r.status == "blocked"


# ── Size cap + timeout, with loop-responsiveness watchdog ────────────────────


@pytest.fixture
async def loop_watchdog() -> AsyncIterator[Callable[[], float]]:
    """Yield a getter for the max gap (seconds) observed between 10 ms samples."""
    max_gap = 0.0
    stop = asyncio.Event()

    async def monitor() -> None:
        nonlocal max_gap
        loop = asyncio.get_running_loop()
        last = loop.time()
        while not stop.is_set():
            await asyncio.sleep(0.01)
            now = loop.time()
            max_gap = max(max_gap, now - last)
            last = now

    task = asyncio.create_task(monitor())
    try:
        yield lambda: max_gap
    finally:
        stop.set()
        await task


class _ChunkStream(httpx.AsyncByteStream):
    """Yields ``count`` chunks cooperatively, counting how many were consumed."""

    def __init__(self, chunk: bytes, count: int) -> None:
        self._chunk = chunk
        self._count = count
        self.yielded = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(self._count):
            self.yielded += 1
            await asyncio.sleep(0)  # keep the loop responsive
            yield self._chunk

    async def aclose(self) -> None:
        pass


async def test_oversize_response_aborted_midstream(
    public_dns: None, loop_watchdog: Callable[[], float]
) -> None:
    stream = _ChunkStream(b"x" * 65536, count=200)  # 12.8 MB available

    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    r = await _run("https://feed.example/big", h, fetch_max_bytes=1_000_000)
    assert r.status == "network_error"
    assert "exceeded" in (r.error or "")
    assert stream.yielded < 200  # aborted before draining the whole body
    assert loop_watchdog() < 0.1  # event loop never blocked >100 ms


async def test_total_timeout(public_dns: None) -> None:
    async def slow_handler(req: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1.0)
        return httpx.Response(200, content=b"<rss/>")

    r = await fetch_feed(
        _Target("https://feed.example/slow"),
        transport=httpx.MockTransport(slow_handler),
        settings=_settings(fetch_timeout_s=0.2),
    )
    assert r.status == "network_error"
    assert r.error == "timeout"
