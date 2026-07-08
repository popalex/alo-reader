"""Seed a large, realistic dataset for the entry list + reading pane (WP-10).

Inserts folders, 20 feeds and ~5k entries (configurable) with mixed read/starred
state directly via the app's models — content is run through the real ingest
sanitizer, including one XSS-probe entry whose script/handlers are stripped so
the reading pane renders it inert.

Idempotent: it resets this user's folders/subscriptions/state and its seeded
feeds first. Runs against DATABASE_URL (AUTH_MODE=none maps every request to the
single user, so the SPA sees this data).

  DATABASE_URL=postgresql+asyncpg://alo:alo@localhost:5432/alo \
    .venv/bin/python scripts/seed_dev.py
  # scale knobs: SEED_ENTRIES_PER_FEED (default 250)

  # inside the compose stack (CI/e2e), no host Python needed:
  docker compose exec -T api python - < scripts/seed_dev.py
"""

import asyncio
import hashlib
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ingest import sanitize_html
from app.models import Entry, EntryState, Feed, Folder, Subscription, User

NOW = datetime.now(timezone.utc)
FEED_URL_PREFIX = "https://seed.dev/feed/"
ENTRIES_PER_FEED = int(os.environ.get("SEED_ENTRIES_PER_FEED", "250"))

FOLDERS = ["Tech", "News", "Science", "Design", "Personal"]

# (folder | None, feed title)
FEED_DEFS = [
    ("Tech", "Hacker News"),
    ("Tech", "The Verge"),
    ("Tech", "Ars Technica"),
    ("Tech", "Simon Willison's Weblog"),
    ("Tech", "LWN.net"),
    ("Tech", "Console.dev"),
    ("News", "BBC News"),
    ("News", "Reuters"),
    ("News", "The Guardian"),
    ("News", "Associated Press"),
    ("Science", "Nature"),
    ("Science", "Quanta Magazine"),
    ("Science", "Scientific American"),
    ("Design", "Smashing Magazine"),
    ("Design", "CSS-Tricks"),
    ("Design", "A List Apart"),
    ("Personal", "Julia Evans"),
    ("Personal", "Dan Luu"),
    (None, "xkcd"),
    (None, "Hacker Noon"),
]

BANK = {
    "Tech": [
        "A new approach to zero-downtime deploys", "The case for boring technology",
        "Rust in the Linux kernel, one year on", "Why we moved off Kubernetes",
        "Understanding database isolation levels", "Local-first software is having a moment",
        "Debugging a memory leak in production", "The hidden cost of microservices",
        "WebGPU is finally here", "How we cut build times in half",
        "A deep dive into HTTP/3", "Postgres full-text search, revisited",
    ],
    "News": [
        "Markets steady as inflation cools", "Central banks weigh their next move",
        "Coastal cities brace for storm season", "Shipping routes shift after delays",
        "A new trade deal reshapes supply chains", "Renewable energy overtakes coal",
        "Talks resume after weeks of deadlock", "Housing costs cool in major metros",
    ],
    "Science": [
        "A sharper image of a distant galaxy", "What fruit flies teach us about sleep",
        "The math behind soap bubbles", "New evidence on ancient migration",
        "Room-temperature superconductors, again", "How forests talk to each other",
        "A better model of ocean currents", "The physics of a perfect free kick",
    ],
    "Design": [
        "Container queries change everything", "Designing for reduced motion",
        "The return of the humble link", "Color systems that scale",
        "Typography for dense interfaces", "Building an accessible date picker",
        "When to break the grid", "A field guide to empty states",
    ],
    "Personal": [
        "A few things I learned about DNS", "Notes on running a local LLM",
        "What I got wrong about caching", "My note-taking setup in 2026",
        "On finishing side projects", "How I debug flaky tests",
        "A year of working in public", "Small tools I can't live without",
    ],
}

RAW_BODIES = [
    "<p>{lead}</p><p>An ordinary paragraph of body text with a "
    '<a href="https://example.com">link</a> and some inline <code>code</code>.</p>'
    "<blockquote>A short pull quote to break up the flow.</blockquote>"
    "<p>A closing paragraph so the reading pane has enough to render.</p>",
    "<p>{lead}</p><ul><li>First point worth noting</li><li>Second point</li>"
    "<li>Third, with a <em>little</em> emphasis</li></ul><p>And a wrap-up line.</p>",
    "<p>{lead}</p><h2>A subheading</h2><p>More detail under the subheading, with a "
    "<code>snippet</code> of code and a normal sentence to finish.</p>",
]

# Original (hostile) content for the XSS probe — sanitized at seed time exactly
# as ingest would, so what lands in the DB is already inert.
XSS_RAW = (
    "<p>Safe intro paragraph for the XSS probe.</p>"
    '<script>window.__xss_fired = true; alert("xss-script");</script>'
    '<img src="x" onerror="window.__xss_fired = true; alert(\'xss-onerror\')">'
    "<a href=\"javascript:window.__xss_fired=true\">do not run</a>"
    "<p>Safe outro paragraph.</p>"
)
XSS_TITLE = "XSS probe: this should render inert"


async def get_or_create_none_user(session) -> User:
    stmt = select(User).where(User.clerk_user_id.is_(None)).order_by(User.id).limit(1)
    user = (await session.scalars(stmt)).first()
    if user is None:
        user = User(clerk_user_id=None, email="")
        session.add(user)
        await session.flush()
    return user


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    Session = async_sessionmaker(engine, expire_on_commit=False)

    bodies = [b.format(lead="This is a seeded article body for the reading pane.") for b in RAW_BODIES]
    safe_bodies = [sanitize_html(b) for b in bodies]
    xss_body = sanitize_html(XSS_RAW)

    async with Session() as session:
        async with session.begin():
            user = await get_or_create_none_user(session)

            seeded_urls = [f"{FEED_URL_PREFIX}{i}" for i in range(len(FEED_DEFS))]
            await session.execute(delete(EntryState).where(EntryState.user_id == user.id))
            await session.execute(delete(Subscription).where(Subscription.user_id == user.id))
            await session.execute(delete(Folder).where(Folder.user_id == user.id))
            await session.execute(delete(Feed).where(Feed.feed_url.in_(seeded_urls)))
            await session.flush()

            folders = {}
            for pos, name in enumerate(FOLDERS):
                f = Folder(user_id=user.id, name=name, position=pos)
                session.add(f)
                folders[name] = f
            await session.flush()

            # Feeds + subscriptions.
            feeds: list[Feed] = []
            for i, (folder_name, title) in enumerate(FEED_DEFS):
                feed = Feed(
                    feed_url=f"{FEED_URL_PREFIX}{i}",
                    site_url=f"https://seed.dev/{i}",
                    title=title,
                    last_error="Connection timed out after 30s" if title == "Reuters" else None,
                    error_count=3 if title == "Reuters" else 0,
                    last_fetched_at=NOW - timedelta(minutes=20),
                    next_check_at=NOW + timedelta(days=365),  # keep the worker off the seed
                )
                session.add(feed)
                feeds.append(feed)
            await session.flush()

            for i, feed in enumerate(feeds):
                folder_name = FEED_DEFS[i][0]
                session.add(
                    Subscription(
                        user_id=user.id,
                        feed_id=feed.id,
                        folder_id=folders[folder_name].id if folder_name else None,
                        since_entry_id=0,
                    )
                )

            # Entries (bulk): oldest first so the newest gets the highest id.
            total = len(feeds) * ENTRIES_PER_FEED
            entries: list[Entry] = []
            g = 0
            for i, feed in enumerate(feeds):
                folder_name = FEED_DEFS[i][0]
                pool = BANK[folder_name] if folder_name in BANK else BANK["Tech"]
                for j in range(ENTRIES_PER_FEED):
                    g += 1
                    created = NOW - timedelta(minutes=2 * (total - g))
                    entries.append(
                        Entry(
                            feed_id=feed.id,
                            guid_hash=hashlib.sha256(f"{feed.id}:{j}".encode()).digest(),
                            url=f"https://seed.dev/{i}/article/{j}",
                            title=f"{pool[j % len(pool)]} #{j + 1}",
                            author=FEED_DEFS[i][1],
                            content_html=safe_bodies[g % len(safe_bodies)],
                            published_at=created - timedelta(minutes=4),
                            created_at=created,
                        )
                    )
            # XSS probe: appended last so it has the highest id — the newest entry
            # in the first feed, and row 0 of the "all" stream (easy for e2e to open).
            entries.append(
                Entry(
                    feed_id=feeds[0].id,
                    guid_hash=hashlib.sha256(f"{feeds[0].id}:xss".encode()).digest(),
                    url="https://seed.dev/0/xss",
                    title=XSS_TITLE,
                    author=FEED_DEFS[0][1],
                    content_html=xss_body,
                    published_at=NOW,
                    created_at=NOW,
                )
            )
            session.add_all(entries)
            await session.flush()

            # State: ~40% read, ~3% starred (skip the XSS probe so it's easy to open unread).
            states: list[EntryState] = []
            for k, e in enumerate(entries):
                if e.title == XSS_TITLE:
                    continue
                is_read = k % 5 < 2
                is_starred = k % 31 == 0
                if is_read or is_starred:
                    states.append(
                        EntryState(
                            user_id=user.id, entry_id=e.id,
                            is_read=is_read, is_starred=is_starred, changed_at=NOW,
                        )
                    )
            session.add_all(states)

    await engine.dispose()
    print(
        f"Seeded {len(feeds)} feeds, {len(entries)} entries, {len(states)} state rows "
        f"for user id={user.id} ({ENTRIES_PER_FEED}/feed)."
    )


if __name__ == "__main__":
    asyncio.run(main())
