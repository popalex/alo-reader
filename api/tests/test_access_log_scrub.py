"""uvicorn's access line carries the query string, and a query string here can
carry somebody's search terms. app/sentry.py already scrubs them before an event
leaves the process; this is the same guarantee for the log."""

import logging

from app.main import _install_access_log_scrubber, _ScrubQueryString


def _record(path: str) -> logging.LogRecord:
    rec = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d', None, None
    )
    rec.args = ("127.0.0.1:1234", "GET", path, "1.1", 200)
    return rec


def test_query_string_is_scrubbed() -> None:
    rec = _record("/api/v1/streams/all/entries?q=my+private+search&limit=50")
    assert _ScrubQueryString().filter(rec) is True
    assert isinstance(rec.args, tuple)
    assert rec.args[2] == "/api/v1/streams/all/entries?[scrubbed]"


def test_paths_without_a_query_are_untouched() -> None:
    rec = _record("/api/v1/entries")
    _ScrubQueryString().filter(rec)
    assert isinstance(rec.args, tuple)
    assert rec.args[2] == "/api/v1/entries"


def test_installation_is_idempotent() -> None:
    access = logging.getLogger("uvicorn.access")
    before = list(access.filters)
    try:
        _install_access_log_scrubber()
        _install_access_log_scrubber()
        assert sum(isinstance(f, _ScrubQueryString) for f in access.filters) == 1
    finally:
        access.filters = before
