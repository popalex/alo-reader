"""The OTLP log handler must not be attached to a logger and one of its ancestors.

Python hands a record to every handler up the logger tree, so a handler attached to
both "uvicorn" and "uvicorn.error" exports each uvicorn.error record twice. That is
what shipped, and in Loki it looked like every line was logged twice: same service
instance, same nanosecond timestamp, two copies.

This needs no OpenTelemetry install: the bug is in the list of names, so the list is
what gets checked, and it runs in the normal test job rather than being skipped for a
missing extra.
"""

from app.telemetry import _LOG_EXPORT_LOGGERS


def _is_ancestor(parent: str, child: str) -> bool:
    """True if `parent` is above `child` in the logger hierarchy (root is above all)."""
    if parent == child:
        return False
    return child.startswith(parent + ".")


def test_no_logger_is_an_ancestor_of_another() -> None:
    overlaps = [
        (a, b) for a in _LOG_EXPORT_LOGGERS for b in _LOG_EXPORT_LOGGERS if _is_ancestor(a, b)
    ]
    assert not overlaps, (
        f"{overlaps} — a handler on both a logger and its ancestor exports every "
        "record twice. Attach to the leaf only."
    )


def test_no_root_logger() -> None:
    """The root logger would receive everything by propagation, duplicating all of it."""
    assert "" not in _LOG_EXPORT_LOGGERS
    assert "root" not in _LOG_EXPORT_LOGGERS


def test_the_loggers_that_matter_are_still_covered() -> None:
    """Guard against 'fixing' the duplication by deleting coverage.

    uvicorn.access and uvicorn.error carry the request log and the tracebacks, and
    uvicorn sets propagate=False on the access logger, so it cannot be covered by an
    ancestor and must be listed explicitly.
    """
    for name in ("alo.api", "worker", "uvicorn.access", "uvicorn.error"):
        assert name in _LOG_EXPORT_LOGGERS, f"{name} would stop reaching Loki"
