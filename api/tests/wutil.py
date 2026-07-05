"""Shared helpers for the worker tests (not a test module — no ``test_`` prefix)."""

import httpx
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Entry, Feed
from app.store import feeds as feeds_store


def worker_settings(**over: object) -> Settings:
    """A Settings with a dummy DB URL (the worker uses an injected session factory)
    and politeness delay off by default so tests stay fast."""
    base: dict[str, object] = {
        "database_url": "postgresql+asyncpg://x/y",
        "auth_mode": "none",
        "worker_per_host_delay_s": 0.0,
        # Keep favicon fetching out of the generic worker tests (they inject a
        # feed-only transport); WP-08's own tests turn it on explicitly.
        "worker_fetch_favicons": False,
    }
    base.update(over)
    return Settings(**base)  # type: ignore[arg-type]


def rss(items: list[tuple[str, str]], *, feed_title: str = "Test Feed") -> bytes:
    """Build a minimal RSS 2.0 body from ``(guid, title)`` pairs."""
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0"><channel>',
        f"<title>{feed_title}</title><link>https://feed.example/</link>",
    ]
    for guid, title in items:
        parts.append(
            f"<item><guid>{guid}</guid><title>{title}</title>"
            f"<description>body of {title}</description></item>"
        )
    parts.append("</channel></rss>")
    return "".join(parts).encode("utf-8")


def serve(body: bytes, *, etag: str = '"v1"') -> httpx.MockTransport:
    """Transport that returns ``body`` with an ETag, or 304 once the client sends a
    matching ``If-None-Match`` — i.e. a well-behaved conditional-GET origin."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("if-none-match") == etag:
            return httpx.Response(304)
        return httpx.Response(200, headers={"ETag": etag}, content=body)

    return httpx.MockTransport(handler)


async def seed_feed(sf: async_sessionmaker[AsyncSession], feed_url: str) -> int:
    async with sf() as s, s.begin():
        feed = await feeds_store.create(s, feed_url=feed_url)
        return feed.id


async def count_entries(sf: async_sessionmaker[AsyncSession], feed_id: int) -> int:
    async with sf() as s:
        result = await s.scalars(
            select(func.count()).select_from(Entry).where(Entry.feed_id == feed_id)
        )
        return result.one()


async def make_due(sf: async_sessionmaker[AsyncSession], feed_id: int) -> None:
    """Mark a feed due again (simulating elapsed time) so the next poll re-claims it."""
    async with sf() as s, s.begin():
        await s.execute(
            update(Feed)
            .where(Feed.id == feed_id)
            .values(next_check_at=text("'epoch'::timestamptz"))
        )


async def get_feed(sf: async_sessionmaker[AsyncSession], feed_id: int) -> Feed:
    async with sf() as s:
        feed = await s.get(Feed, feed_id)
        assert feed is not None
        return feed
