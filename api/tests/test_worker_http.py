"""guarded_get streaming/size behavior (shared by discovery + favicons)."""

import httpx
import pytest

from app.worker.http import guarded_get

from . import wutil

pytestmark = pytest.mark.usefixtures("public_dns")

_BIG = b'<?xml version="1.0"?><rss version="2.0"><channel>' + b"x" * 10_000


def _transport() -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda req: httpx.Response(200, content=_BIG, headers={"content-type": "text/xml"})
    )


async def test_oversize_without_truncate_is_an_error() -> None:
    r = await guarded_get(
        "https://big.example/feed",
        max_bytes=1000,
        settings=wutil.worker_settings(),
        transport=_transport(),
    )
    assert not r.ok
    assert "exceeded" in (r.error or "")


async def test_truncate_returns_capped_head_ok() -> None:
    # A big feed must still be *fetchable* for discovery: truncate keeps the head
    # (enough to detect <rss>) and returns ok instead of failing.
    r = await guarded_get(
        "https://big.example/feed",
        max_bytes=1000,
        settings=wutil.worker_settings(),
        transport=_transport(),
        truncate=True,
    )
    assert r.ok
    assert r.body is not None and len(r.body) == 1000
    assert r.body.startswith(b'<?xml version="1.0"?><rss version="2.0"')
