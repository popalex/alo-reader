"""Worker (poller) entrypoint — claim loop, scheduling, persistence (DESIGN.md §1.3).

The ``worker`` command runs :func:`run`: every few seconds it claims a batch of due
feeds under a lease (``FOR UPDATE SKIP LOCKED``, so N replicas never collide), then
fetches + persists them concurrently under a global cap and a per-host politeness
gate. It shuts down cleanly on SIGTERM/SIGINT — finishing the in-flight batch (which
releases those leases) and leaving any unclaimed work for the next tick or replica.

:func:`poll_once` is one claim+process cycle, factored out so it can be driven
directly in tests without the surrounding loop or signal handling.
"""

import asyncio
import logging
import signal
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.db import get_sessionmaker
from app.models import Feed
from app.store import feeds as feeds_store
from app.worker.fetch import fetch_feed
from app.worker.maintenance import maintenance_loop
from app.worker.pipeline import FeedOutcome, FetchFn, process_feed

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


def _log(event: str, **fields: object) -> None:
    """Emit a structured ``key=value`` line to stdout."""
    tail = " ".join(f"{k}={v}" for k, v in fields.items())
    log.info("%s %s", event, tail)


@dataclass
class Counters:
    """Cumulative poll counters, kept for a later ``/metrics`` (WP-16)."""

    polls: int = 0
    new_body: int = 0
    not_modified: int = 0
    errors: int = 0
    entries_inserted: int = 0

    def record(self, outcome: FeedOutcome) -> None:
        self.polls += 1
        if outcome.status == "new_body":
            self.new_body += 1
            self.entries_inserted += outcome.new_entries
        elif outcome.status == "not_modified":
            self.not_modified += 1
        else:
            self.errors += 1


# Sweep out per-host bookkeeping for hosts idle at least this long. Without it the
# gate's maps grow one entry per distinct host for the life of the worker.
_HOST_GATE_PRUNE_INTERVAL_S = 300.0


class HostGate:
    """Per-origin-host concurrency limit plus a minimum spacing between fetches."""

    def __init__(self, concurrency: int, delay_s: float) -> None:
        self._concurrency = max(1, concurrency)
        self._delay = delay_s
        self._sems: dict[str, asyncio.Semaphore] = {}
        self._next_allowed: dict[str, float] = {}
        self._active: dict[str, int] = {}  # in-flight slot holders per host
        self._last_prune = 0.0

    @asynccontextmanager
    async def slot(self, host: str) -> AsyncIterator[None]:
        sem = self._sems.setdefault(host, asyncio.Semaphore(self._concurrency))
        self._active[host] = self._active.get(host, 0) + 1
        try:
            async with sem:
                loop = asyncio.get_running_loop()
                if self._delay > 0:
                    wait = self._next_allowed.get(host, 0.0) - loop.time()
                    if wait > 0:
                        await asyncio.sleep(wait)
                try:
                    yield
                finally:
                    if self._delay > 0:
                        self._next_allowed[host] = asyncio.get_running_loop().time() + self._delay
        finally:
            if (remaining := self._active[host] - 1) > 0:
                self._active[host] = remaining
            else:
                del self._active[host]
            self._prune()

    def _prune(self) -> None:
        """Drop bookkeeping for hosts with no in-flight fetch whose spacing window has
        elapsed. Such a host recreates its state (a fresh full semaphore, no pending
        delay) identically on next use, so pruning is behavior-preserving."""
        now = asyncio.get_running_loop().time()
        if now - self._last_prune < _HOST_GATE_PRUNE_INTERVAL_S:
            return
        self._last_prune = now
        idle = [
            h
            for h in list(self._sems)
            if h not in self._active and self._next_allowed.get(h, 0.0) <= now
        ]
        for h in idle:
            self._sems.pop(h, None)
            self._next_allowed.pop(h, None)


def _host(feed_url: str) -> str:
    return urlsplit(feed_url).hostname or ""


async def poll_once(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    fetch: FetchFn = fetch_feed,
    transport: object | None = None,
    gate: HostGate | None = None,
    counters: Counters | None = None,
) -> int:
    """Claim one batch of due feeds and process them. Returns the batch size."""
    async with session_factory() as session, session.begin():
        feeds = await feeds_store.claim_due_feeds(
            session, limit=settings.worker_claim_batch, lease_seconds=settings.worker_lease_s
        )
    if not feeds:
        return 0

    gate = gate or HostGate(settings.worker_per_host_concurrency, settings.worker_per_host_delay_s)
    counters = counters if counters is not None else Counters()
    global_sem = asyncio.Semaphore(settings.worker_max_concurrency)

    async def _run_one(feed: Feed) -> None:
        try:
            async with global_sem, gate.slot(_host(feed.feed_url)):
                outcome = await process_feed(
                    session_factory,
                    feed,  # type: ignore[arg-type]  # Feed satisfies FeedRow structurally
                    settings=settings,
                    fetch=fetch,
                    transport=transport,  # type: ignore[arg-type]
                )
            counters.record(outcome)
            _log("feed_polled", feed_id=feed.id, status=outcome.status, new=outcome.new_entries)
        except Exception as exc:  # one bad feed must not sink the batch
            counters.errors += 1
            _log("feed_failed", feed_id=feed.id, error=repr(exc))

    async with asyncio.TaskGroup() as tg:
        for feed in feeds:
            tg.create_task(_run_one(feed))
    return len(feeds)


async def run(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    stop: asyncio.Event | None = None,
) -> Counters:
    """Run the claim loop until stopped. Returns the accumulated counters.

    Production passes nothing and gets SIGTERM/SIGINT-driven shutdown; tests inject
    ``settings``/``session_factory``/``stop`` and drive the ``stop`` event directly.
    """
    settings = settings or get_settings()
    session_factory = session_factory or get_sessionmaker()
    gate = HostGate(settings.worker_per_host_concurrency, settings.worker_per_host_delay_s)
    counters = Counters()

    # Only wire OS signals on the production path (no caller-provided stop event);
    # a test supplying its own stop must not clobber the interpreter's handlers.
    own_stop = stop is None
    stop = stop or asyncio.Event()
    if own_stop:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

    async def _claim_loop() -> None:
        while not stop.is_set():
            try:
                await poll_once(session_factory, settings=settings, gate=gate, counters=counters)
            except Exception as exc:  # never let the loop die on a transient DB blip
                _log("poll_cycle_failed", error=repr(exc))
            if stop.is_set():
                break
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_interval_s)
            except TimeoutError:
                pass

    async def _supervise(name: str, coro: Awaitable[None]) -> None:
        """Run a loop; if it dies, log it and set ``stop`` so its sibling also drains
        rather than being left running as an orphan (graceful shutdown preserved)."""
        try:
            await coro
        except Exception as exc:  # noqa: BLE001 — a crashing loop must not strand the other
            _log(f"{name}_crashed", error=repr(exc))
        finally:
            stop.set()

    _log("worker_started", poll_interval_s=settings.worker_poll_interval_s)
    # The claim loop and the periodic maintenance sweep run concurrently, both watching
    # the same stop event so SIGTERM — or either loop failing — drains everything.
    sweep = maintenance_loop(session_factory, settings=settings, stop=stop)
    await asyncio.gather(
        _supervise("claim_loop", _claim_loop()),
        _supervise("maintenance_loop", sweep),
    )
    _log(
        "worker_stopped",
        polls=counters.polls,
        new_body=counters.new_body,
        not_modified=counters.not_modified,
        errors=counters.errors,
        entries=counters.entries_inserted,
    )
    return counters


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
