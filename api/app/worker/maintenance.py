"""Worker-embedded periodic maintenance (WP-15, DESIGN.md §0.3, §1.3).

Two housekeeping jobs run inside the worker process on a jittered interval:

* **Orphan-feed GC** — a globally-deduped feed with zero subscribers past the grace
  period is dead weight; delete it (its entries cascade).
* **Retention purge** — read + unstarred entries older than the horizon whose every
  subscriber has read them are removed; starred are kept forever, unread never purged.

The interval is jittered so multiple workers don't all sweep at the same instant.
Each job runs in its own transaction; a failure in one is logged and never sinks the
loop or the other job.
"""

import asyncio
import random
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.store import entries as entries_store
from app.store import feeds as feeds_store
from app.worker.log import emit as _log

_DEFAULT_RNG = random.Random()


def next_wait(settings: Settings, rng: random.Random | None = None) -> float:
    """Jittered delay until the next maintenance sweep, clamped to ``>= 0``."""
    r = rng or _DEFAULT_RNG
    jitter = r.uniform(-settings.worker_maintenance_jitter_s, settings.worker_maintenance_jitter_s)
    return max(0.0, settings.worker_maintenance_interval_s + jitter)


async def run_maintenance(
    session_factory: async_sessionmaker[AsyncSession], *, settings: Settings
) -> tuple[int, int]:
    """Run one GC + purge sweep. Returns ``(feeds_gc'd, entries_purged)``."""
    gc = 0
    purged = 0
    try:
        async with session_factory() as session, session.begin():
            gc = await feeds_store.delete_orphaned(
                session, grace=timedelta(days=settings.orphan_grace_days)
            )
    except Exception as exc:  # noqa: BLE001 — never let GC failure sink the loop
        _log("orphan_gc_failed", error=repr(exc))
    horizon = timedelta(days=settings.retention_horizon_days)
    batch = settings.retention_purge_batch_size
    try:
        # Purge in bounded batches, each its own transaction, so a large backlog
        # never locks/rewrites the whole entries table in one long-held statement.
        while True:
            async with session_factory() as session, session.begin():
                n = await entries_store.purge_retained(session, horizon=horizon, limit=batch)
            purged += n
            if n < batch:
                break
    except Exception as exc:  # noqa: BLE001
        _log("retention_purge_failed", error=repr(exc))
    _log("maintenance_swept", feeds_gc=gc, entries_purged=purged)
    return gc, purged


async def maintenance_loop(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    """Run :func:`run_maintenance` on a jittered interval until ``stop`` is set.

    Sleeps first (jittered), so a fleet of freshly-started workers staggers rather
    than stampeding the DB on boot."""
    _log("maintenance_started", interval_s=settings.worker_maintenance_interval_s)
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=next_wait(settings))
        except TimeoutError:
            pass
        if stop.is_set():
            break
        await run_maintenance(session_factory, settings=settings)
