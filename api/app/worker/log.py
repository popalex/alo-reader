"""Shared worker logging: the ``worker`` logger plus a structured key=value emitter,
used by the claim loop, the maintenance loop, and the pipeline so the format can't drift.
"""

import logging

from app.logfmt import line

log = logging.getLogger("worker")


def emit(event: str, **fields: object) -> None:
    """Emit a structured ``event key=value …`` line to the worker log."""
    log.info("%s", line(event, **fields))
