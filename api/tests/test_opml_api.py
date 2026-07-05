"""OPML export/import: round-trip equality, real-world fixtures, guards (WP-08)."""

from pathlib import Path

import httpx
from sqlalchemy import select

from app import db as app_db
from app.models import Feed, Folder, Subscription

from .conftest import PatUser, make_pat_user

OPML = "/api/v1/opml"
SUBS = "/api/v1/subscriptions"
FOLDERS = "/api/v1/folders"
FIXTURES = Path(__file__).parent / "fixtures" / "opml"


async def _subscribe(
    client: httpx.AsyncClient, h: dict[str, str], url: str, folder: int | None
) -> None:
    body: dict[str, object] = {"feed_url": url}
    if folder is not None:
        body["folder_id"] = folder
    resp = await client.post(SUBS, json=body, headers=h)
    assert resp.status_code == 201


async def _structure(user_id: int) -> dict[str, set[str]]:
    """Map folder name ('' for none) -> set of feed_urls, the semantic identity of a
    user's subscriptions (read straight from the DB, independent of poll state)."""
    async with app_db.get_sessionmaker()() as s:
        rows = (
            await s.execute(
                select(Folder.name, Feed.feed_url)
                .select_from(Subscription)
                .join(Feed, Feed.id == Subscription.feed_id)
                .outerjoin(Folder, Folder.id == Subscription.folder_id)
                .where(Subscription.user_id == user_id)
            )
        ).all()
    out: dict[str, set[str]] = {}
    for name, feed_url in rows:
        out.setdefault(name or "", set()).add(feed_url)
    return out


async def test_export_import_round_trip(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    h = pat_user.headers
    tech = (await api_client.post(FOLDERS, json={"name": "Tech"}, headers=h)).json()["id"]
    await _subscribe(api_client, h, "https://a.example/rss", tech)
    await _subscribe(api_client, h, "https://b.example/rss", tech)
    await _subscribe(api_client, h, "https://solo.example/rss", None)

    export = await api_client.get(OPML, headers=h)
    assert export.status_code == 200
    assert "opml" in export.headers["content-type"]
    opml_bytes = export.content

    # Import into a fresh user; the folder structure must survive.
    other = await make_pat_user("import@example.com")
    report = await api_client.post(
        OPML, files={"file": ("export.opml", opml_bytes, "text/x-opml")}, headers=other.headers
    )
    assert report.status_code == 200
    body = report.json()
    assert body["imported"] == 3 and body["skipped"] == 0 and body["failed"] == []

    assert await _structure(other.user_id) == await _structure(pat_user.user_id)


async def test_reimport_is_idempotent_skips_dups(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    h = pat_user.headers
    await _subscribe(api_client, h, "https://a.example/rss", None)
    opml_bytes = (await api_client.get(OPML, headers=h)).content

    report = await api_client.post(
        OPML, files={"file": ("x.opml", opml_bytes, "text/x-opml")}, headers=h
    )
    body = report.json()
    assert body["imported"] == 0 and body["skipped"] == 1  # already subscribed


async def test_feedly_fixture_imports(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    data = (FIXTURES / "feedly.opml").read_bytes()
    report = await api_client.post(
        OPML, files={"file": ("feedly.opml", data, "text/x-opml")}, headers=pat_user.headers
    )
    body = report.json()
    assert body["imported"] == 4 and body["failed"] == []
    structure = await _structure(pat_user.user_id)
    assert structure["Tech"] == {
        "https://www.theverge.com/rss/index.xml",
        "https://feeds.arstechnica.com/arstechnica/index",
    }
    assert structure["News"] == {"https://feeds.bbci.co.uk/news/rss.xml"}
    assert structure[""] == {"https://xkcd.com/rss.xml"}  # top-level feed


async def test_miniflux_fixture_imports(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    data = (FIXTURES / "miniflux.opml").read_bytes()
    report = await api_client.post(
        OPML, files={"file": ("miniflux.opml", data, "text/x-opml")}, headers=pat_user.headers
    )
    body = report.json()
    assert body["imported"] == 3 and body["failed"] == []
    structure = await _structure(pat_user.user_id)
    assert structure["Programming"] == {"https://jvns.ca/atom.xml", "https://danluu.com/atom.xml"}
    assert structure["Uncategorized"] == {"https://simonwillison.net/atom/everything/"}


async def test_import_reports_quota(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    from sqlalchemy import update

    from app import db as app_db
    from app.models import User

    async with app_db.get_sessionmaker()() as s, s.begin():
        await s.execute(update(User).where(User.id == pat_user.user_id).values(quota_subs=1))

    data = (FIXTURES / "feedly.opml").read_bytes()  # 4 feeds, quota 1
    body = (
        await api_client.post(
            OPML, files={"file": ("f.opml", data, "text/x-opml")}, headers=pat_user.headers
        )
    ).json()
    assert body["imported"] == 1
    assert len(body["failed"]) == 3
    assert all(f["reason"] == "quota exceeded" for f in body["failed"])


async def test_import_rejects_oversize(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    big = b"<opml><body>" + b"<!-- pad -->" * 200_000 + b"</body></opml>"  # > 1 MB
    resp = await api_client.post(
        OPML, files={"file": ("big.opml", big, "text/x-opml")}, headers=pat_user.headers
    )
    assert resp.status_code == 422


async def test_import_rejects_entities(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "boom">]><opml><body/></opml>'
    resp = await api_client.post(
        OPML, files={"file": ("b.opml", bomb, "text/x-opml")}, headers=pat_user.headers
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"


async def test_import_malformed_is_400(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    resp = await api_client.post(
        OPML, files={"file": ("m.opml", b"<opml><body", "text/x-opml")}, headers=pat_user.headers
    )
    assert resp.status_code == 400
