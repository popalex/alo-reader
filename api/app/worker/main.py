"""Worker (poller) entrypoint — stub for WP-00.

The real claim loop, fetch/parse/sanitize pipeline, and scheduling land in WP-05.
For now this is a heartbeat loop so the ``worker`` command in the Docker image is
runnable and exits cleanly on SIGTERM.
"""

import asyncio
import logging
import signal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")

TICK_SECONDS = 5.0


async def run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    log.info("worker started")
    while not stop.is_set():
        log.info("tick")
        try:
            await asyncio.wait_for(stop.wait(), timeout=TICK_SECONDS)
        except TimeoutError:
            pass
    log.info("worker stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
