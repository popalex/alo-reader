"""Unread counts asserted against an independent brute-force recomputation."""

import random
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.store import counts as counts_store
from app.store import entry_states as states_store
from tests.factories import add_entries, make_feed, make_subscription, make_user


async def test_unread_counts_match_bruteforce(session: AsyncSession) -> None:
    now = datetime.now(UTC)

    for seed in range(3):  # ≥3 randomized seedings
        rng = random.Random(seed)
        user = await make_user(session)
        expected: dict[int, int] = {}
        expected_total = 0

        for _ in range(rng.randint(2, 4)):
            feed = await make_feed(session)
            sub = await make_subscription(session, user, feed)
            ents = await add_entries(session, feed, rng.randint(0, 8))

            # Optionally advance since_entry_id to some entry (predates → not unread).
            since = 0
            if ents and rng.random() < 0.5:
                since = ents[rng.randint(0, len(ents) - 1)].id
                sub.since_entry_id = since
                await session.flush()

            unread = 0
            for e in ents:
                read = rng.random() < 0.4
                if read:
                    await states_store.upsert(session, user.id, e.id, changed_at=now, is_read=True)
                if e.id > since and not read:
                    unread += 1
            expected[sub.id] = unread
            expected_total += unread

        counts = await counts_store.unread_counts(session, user.id)
        assert counts.per_subscription == expected
        assert counts.total == expected_total
