"""Graceful shutdown + task hygiene (DESIGN.md §1.3 async foot-guns).

The loop must stop promptly on its stop event and leak no tasks; one poll cycle
must await all of its per-feed work (asyncio.TaskGroup) before returning.
"""

import asyncio

import httpx
import pytest

from app import db as app_db
from app.worker.main import poll_once, run
from tests import wutil

pytestmark = pytest.mark.usefixtures("public_dns")

_ITEMS = [("g1", "One"), ("g2", "Two")]


async def test_run_loops_and_stops_on_event(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    stop = asyncio.Event()
    settings = wutil.worker_settings(worker_poll_interval_s=0.02)

    task = asyncio.create_task(run(settings=settings, session_factory=sf, stop=stop))
    await asyncio.sleep(0.1)  # let it spin several idle cycles
    stop.set()
    counters = await asyncio.wait_for(task, timeout=2.0)

    assert task.done() and not task.cancelled()
    assert counters.polls == 0  # no feeds were due


async def test_poll_once_leaves_no_pending_tasks(api_db: str) -> None:
    sf = app_db.get_sessionmaker()
    for i in range(5):
        await wutil.seed_feed(sf, f"https://feed{i}.example/rss")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, content=wutil.rss(_ITEMS)))

    before = asyncio.all_tasks()
    processed = await poll_once(sf, settings=wutil.worker_settings(), transport=transport)
    after = {t for t in asyncio.all_tasks() if not t.done()}

    assert processed == 5
    # TaskGroup awaited every per-feed task; nothing new is left running.
    assert after <= before | {asyncio.current_task()}
