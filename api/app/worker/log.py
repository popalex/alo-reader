"""Shared worker logging: the ``worker`` logger plus a structured key=value emitter,
used by the claim loop, the maintenance loop, and the pipeline so the format can't drift.
"""

import logging

log = logging.getLogger("worker")


def emit(event: str, **fields: object) -> None:
    """Emit a structured ``event key=value …`` line to the worker log."""
    tail = " ".join(f"{k}={v}" for k, v in fields.items())
    log.info("%s %s", event, tail)
