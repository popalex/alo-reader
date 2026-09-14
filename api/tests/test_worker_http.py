"""guarded_get streaming/size behavior (shared by discovery + favicons)."""

import httpx
import pytest

from app.worker.fetch import _parse_retry_after
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


async def test_retry_after_with_a_superscript_digit_does_not_raise() -> None:
    # str.isdigit() is true for "2" while float() refuses it, and the check sits
    # outside the try below, so this used to escape fetch_feed entirely: a 429 with a
    # junk Retry-After became an unhandled failure with no backoff recorded.
    assert _parse_retry_after("²") is None
    assert _parse_retry_after("120") == 120.0
    assert _parse_retry_after("not a number") is None
