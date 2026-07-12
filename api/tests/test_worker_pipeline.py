"""End-to-end worker pipeline against the test DB (DESIGN.md §1.3).

Real parse → sanitize → dedup → persist; only the network is mocked (httpx
MockTransport + the ``public_dns`` resolver). Exercises the exactly-once guarantee,
dedup, error backoff, and permanent-redirect handling.
"""

import httpx
import pytest
from sqlalchemy import text, update

from app import db as app_db
from app.models import Feed
from app.store import metrics as metrics_store
from app.worker.main import Counters, poll_once
from tests import wutil

pytestmark = pytest.mark.usefixtures("public_dns")

_ITEMS = [("g1", "One"), ("g2", "Two"), ("g3", "Three")]


async def test_new_body_then_304_inserts_exactly_once(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    feed_id = await wutil.seed_feed(sf, "https://feed.example/rss")
    transport = wutil.serve(wutil.rss(_ITEMS))
    settings = wutil.worker_settings()
    counters = Counters()

    n = await poll_once(sf, settings=settings, transport=transport, counters=counters)
    assert n == 1
    assert await wutil.count_entries(sf, feed_id) == 3
    assert counters.new_body == 1 and counters.entries_inserted == 3

    # Second cycle (feed due again): the stored ETag drives a 304 — no new rows.
    await wutil.make_due(sf, feed_id)
    await poll_once(sf, settings=settings, transport=transport, counters=counters)
    assert await wutil.count_entries(sf, feed_id) == 3
    assert counters.not_modified == 1

    feed = await wutil.get_feed(sf, feed_id)
    assert feed.error_count == 0
    assert feed.last_error is None
    assert feed.etag == '"v1"'


async def test_fetch_outcome_recorded_to_metrics(api_db: str) -> None:
    # The pipeline records the fetch outcome into the /metrics counters in its own
    # transaction, decoupled from the ingest commit — the happy path must still count.
    sf = app_db.get_sessionmaker()
    await wutil.seed_feed(sf, "https://feed.example/rss")
    transport = wutil.serve(wutil.rss(_ITEMS))

    await poll_once(sf, settings=wutil.worker_settings(), transport=transport)

    async with sf() as s:
        counters = {(c.name, c.label): c.value for c in await metrics_store.all_counters(s)}
    assert counters[(metrics_store.FETCH_OUTCOMES, 'class="new_body"')] == 1


async def test_dedup_when_server_ignores_conditional(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    feed_id = await wutil.seed_feed(sf, "https://feed.example/rss")
    body = wutil.rss(_ITEMS)

    # A rude origin that always 200s with the same items on every poll.
    always_200 = httpx.MockTransport(lambda req: httpx.Response(200, content=body))
    settings = wutil.worker_settings()

    await poll_once(sf, settings=settings, transport=always_200)
    await wutil.make_due(sf, feed_id)  # due again; server still 200s the same items
    await poll_once(sf, settings=settings, transport=always_200)
    assert await wutil.count_entries(sf, feed_id) == 3  # (feed_id, guid_hash) dedup


async def test_http_error_sets_backoff_and_last_error(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    feed_id = await wutil.seed_feed(sf, "https://feed.example/boom")
    transport = httpx.MockTransport(lambda req: httpx.Response(500))
    settings = wutil.worker_settings(worker_backoff_base_s=60)

    await poll_once(sf, settings=settings, transport=transport)

    feed = await wutil.get_feed(sf, feed_id)
    assert feed.error_count == 1
    assert "500" in (feed.last_error or "")
    assert await wutil.count_entries(sf, feed_id) == 0


async def test_permanent_redirect_updates_feed_url(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    feed_id = await wutil.seed_feed(sf, "https://old.example/rss")
    body = wutil.rss(_ITEMS)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "old.example":
            return httpx.Response(301, headers={"Location": "https://new.example/rss"})
        return httpx.Response(200, headers={"ETag": '"v1"'}, content=body)

    await poll_once(sf, settings=wutil.worker_settings(), transport=httpx.MockTransport(handler))

    feed = await wutil.get_feed(sf, feed_id)
    assert feed.feed_url == "https://new.example/rss"
    assert await wutil.count_entries(sf, feed_id) == 3


async def test_permanent_redirect_collision_marks_error(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    # The redirect target already exists as another feed.
    await wutil.seed_feed(sf, "https://new.example/rss")
    moved_id = await wutil.seed_feed(sf, "https://old.example/rss")
    # Only the moved feed is due (park the pre-existing target in the future).
    async with sf() as s, s.begin():
        await s.execute(
            update(Feed)
            .where(Feed.feed_url == "https://new.example/rss")
            .values(next_check_at=text("now() + interval '1 hour'"))
        )

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "old.example":
            return httpx.Response(301, headers={"Location": "https://new.example/rss"})
        return httpx.Response(200, headers={"ETag": '"v1"'}, content=wutil.rss(_ITEMS))

    await poll_once(sf, settings=wutil.worker_settings(), transport=httpx.MockTransport(handler))

    moved = await wutil.get_feed(sf, moved_id)
    assert moved.feed_url == "https://old.example/rss"  # not silently merged
    assert moved.error_count == 1
    assert "already exists" in (moved.last_error or "")
