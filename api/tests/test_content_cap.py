"""Entry content cap (WP-15, DESIGN.md §1.4): 500 KB post-sanitize, truncate + flag.

Asserts the byte cap, the truncation flag, that a severed tag is repaired (output
stays valid allowlisted HTML), and that the flag is persisted through the ingest
pipeline into the ``entries.content_truncated`` column.
"""

from sqlalchemy import select

from app import db as app_db
from app.ingest import sanitize_and_cap
from app.ingest.sanitize import MAX_CONTENT_BYTES
from app.models import Entry
from app.store import entries as entries_store
from app.worker.pipeline import _build_entries


def test_under_cap_is_not_flagged() -> None:
    html, truncated = sanitize_and_cap("<p>small body</p>")
    assert truncated is False
    assert html == "<p>small body</p>"


def test_over_cap_truncates_and_flags() -> None:
    big = "<p>" + ("A" * (MAX_CONTENT_BYTES + 50_000)) + "</p>"
    html, truncated = sanitize_and_cap(big)
    assert truncated is True
    assert len(html.encode("utf-8")) <= MAX_CONTENT_BYTES


def test_truncation_repairs_severed_tag() -> None:
    # A huge run of tiny <b> tags: the byte cut will land mid-tag; the re-clean must
    # leave no partial/dangling tag behind.
    body = "<div>" + ("<b>x</b>" * 200_000) + "</div>"
    html, truncated = sanitize_and_cap(body)
    assert truncated is True
    # Re-sanitizing the output is a no-op → it is already valid, allowlisted HTML.
    assert sanitize_and_cap(html)[0] == html
    assert "<b" not in html.rsplit(">", 1)[-1]  # nothing dangling after the last tag


def test_multibyte_truncation_stays_valid_utf8() -> None:
    body = "<p>" + ("€" * MAX_CONTENT_BYTES) + "</p>"  # 3 bytes each
    html, truncated = sanitize_and_cap(body)
    assert truncated is True
    html.encode("utf-8")  # must not raise — no partial codepoint survived


def test_empty_is_not_flagged() -> None:
    assert sanitize_and_cap("") == ("", False)


def test_pipeline_flags_oversized_entry() -> None:
    big_html = "<p>" + ("word " * 200_000) + "</p>"  # ~1 MB, over the cap
    body = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>F</title>'
        b"<item><guid>huge</guid><title>Huge</title><description><![CDATA["
        + big_html.encode()
        + b"]]></description></item>"
        b"<item><guid>small</guid><title>Small</title>"
        b"<description>tiny</description></item>"
        b"</channel></rss>"
    )
    _, rows = _build_entries(body, max_entries=2000)
    by_title = {r["title"]: r for r in rows}
    assert by_title["Huge"]["content_truncated"] is True
    assert len(by_title["Huge"]["content_html"].encode("utf-8")) <= MAX_CONTENT_BYTES
    assert by_title["Small"]["content_truncated"] is False


def test_entries_per_fetch_cap_keeps_newest() -> None:
    """A feed with more items than the cap keeps only the newest N by publish date."""
    # Items dated Jan 1..10 2024 (i → day i+1).
    items = "".join(
        f"<item><guid>g{i}</guid><title>T{i}</title>"
        f"<pubDate>{i + 1:02d} Jan 2024 00:00:00 GMT</pubDate></item>"
        for i in range(10)
    )
    body = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>F</title>'
        + items.encode()
        + b"</channel></rss>"
    )
    _, rows = _build_entries(body, max_entries=3)
    assert len(rows) == 3  # capped
    kept_days = sorted(
        (r["published_at"].day for r in rows if r["published_at"] is not None), reverse=True
    )
    assert kept_days == [10, 9, 8]  # the newest three by publish date


async def test_truncated_flag_persists_to_db(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    async with sf() as s, s.begin():
        from app.store import feeds as feeds_store

        feed = await feeds_store.create(s, feed_url="https://cap.example/rss")
        feed_id = feed.id
    async with sf() as s, s.begin():
        await entries_store.insert_batch(
            s,
            feed_id,
            [
                {"guid_hash": b"\x01" * 32, "content_html": "<p>x</p>", "content_truncated": True},
                {"guid_hash": b"\x02" * 32, "content_html": "<p>y</p>", "content_truncated": False},
            ],
        )
    async with sf() as s:
        flags = dict(
            (bytes(gh), t)
            for gh, t in (
                await s.execute(
                    select(Entry.guid_hash, Entry.content_truncated).where(Entry.feed_id == feed_id)
                )
            ).all()
        )
    assert flags[b"\x01" * 32] is True
    assert flags[b"\x02" * 32] is False  # server default
