"""Feed discovery endpoint (WP-08). The guarded page fetch is stubbed with fixture
HTML (SSRF/transport are covered elsewhere); this exercises parsing + shaping."""

from pathlib import Path

import httpx
import pytest

from app.routes import discover as discover_mod
from app.worker.http import GetResult

from .conftest import PatUser

DISCOVER = "/api/v1/discover"
HTML = Path(__file__).parent / "fixtures" / "html"


def _stub_get(
    monkeypatch: pytest.MonkeyPatch, body: bytes, *, final_url: str, ok: bool = True
) -> None:
    async def fake(url: str, **kwargs: object) -> GetResult:
        return GetResult(
            ok=ok,
            status=200 if ok else 502,
            body=body if ok else None,
            content_type="text/html",
            final_url=final_url,
        )

    monkeypatch.setattr(discover_mod, "guarded_get", fake)


async def test_discovers_multiple_link_tags(
    api_client: httpx.AsyncClient, pat_user: PatUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_get(
        monkeypatch,
        (HTML / "wordpress.html").read_bytes(),
        final_url="https://blog.example.com/",
    )
    resp = await api_client.post(
        DISCOVER, json={"url": "https://blog.example.com/"}, headers=pat_user.headers
    )
    assert resp.status_code == 200
    urls = {c["feed_url"] for c in resp.json()}
    assert "https://blog.example.com/feed/" in urls
    assert "https://blog.example.com/comments/feed/" in urls


async def test_resolves_relative_feed_href(
    api_client: httpx.AsyncClient, pat_user: PatUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_get(
        monkeypatch,
        (HTML / "relative_atom.html").read_bytes(),
        final_url="https://site.example/blog/",
    )
    resp = await api_client.post(
        DISCOVER, json={"url": "https://site.example/blog/"}, headers=pat_user.headers
    )
    candidates = resp.json()
    assert candidates == [
        {"feed_url": "https://site.example/blog/atom.xml", "title": "Relative Atom Site"}
    ]


async def test_falls_back_to_conventional_paths(
    api_client: httpx.AsyncClient, pat_user: PatUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_get(
        monkeypatch, (HTML / "no_feeds.html").read_bytes(), final_url="https://plain.example/"
    )
    resp = await api_client.post(
        DISCOVER, json={"url": "https://plain.example/"}, headers=pat_user.headers
    )
    urls = {c["feed_url"] for c in resp.json()}
    assert urls == {
        "https://plain.example/feed",
        "https://plain.example/rss",
        "https://plain.example/atom.xml",
        "https://plain.example/index.xml",
    }


async def test_url_that_is_itself_a_feed(
    api_client: httpx.AsyncClient, pat_user: PatUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    rss = (
        b'<?xml version="1.0"?><rss version="2.0">'
        b"<channel><title>Direct Feed</title></channel></rss>"
    )
    _stub_get(monkeypatch, rss, final_url="https://feed.example/rss.xml")
    resp = await api_client.post(
        DISCOVER, json={"url": "https://feed.example/rss.xml"}, headers=pat_user.headers
    )
    assert resp.json() == [{"feed_url": "https://feed.example/rss.xml", "title": "Direct Feed"}]


async def test_unreachable_page_returns_empty(
    api_client: httpx.AsyncClient, pat_user: PatUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_get(monkeypatch, b"", final_url="https://down.example/", ok=False)
    resp = await api_client.post(
        DISCOVER, json={"url": "https://down.example/"}, headers=pat_user.headers
    )
    assert resp.status_code == 200 and resp.json() == []


async def test_bad_url_is_400(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    resp = await api_client.post(DISCOVER, json={"url": "not-a-url"}, headers=pat_user.headers)
    assert resp.status_code == 400
