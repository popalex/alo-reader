"""A search term must not reach the trace store either.

app/main.py scrubs the access log and app/sentry.py scrubs error events; the
FastAPI instrumentation puts the same URL on the server span, which the batch
processor ships to Tempo. This covers that third door.
"""

from typing import Any

from app.telemetry import _scrub_span_query_string


class _FakeSpan:
    """Enough of a Span for the hook: recording, readable and writable attributes."""

    def __init__(self, attributes: dict[str, Any], recording: bool = True) -> None:
        self.attributes = attributes
        self._recording = recording

    def is_recording(self) -> bool:
        return self._recording

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value


def _scope(path: str, query: bytes) -> dict[str, Any]:
    return {"type": "http", "path": path, "query_string": query}


def test_query_string_is_scrubbed_from_every_url_attribute() -> None:
    span = _FakeSpan(
        {
            "http.target": "/api/v1/streams/all/entries?q=private+terms&limit=50",
            "http.url": "http://alo.example/api/v1/streams/all/entries?q=private+terms",
            "url.query": "q=private+terms&limit=50",
        }
    )
    _scrub_span_query_string(span, _scope("/api/v1/streams/all/entries", b"q=private+terms"))
    assert span.attributes["http.target"] == "/api/v1/streams/all/entries?[scrubbed]"
    assert span.attributes["http.url"] == "http://alo.example/api/v1/streams/all/entries?[scrubbed]"
    assert span.attributes["url.query"] == "[scrubbed]"
    assert "private" not in str(span.attributes)


def test_requests_without_a_query_are_untouched() -> None:
    span = _FakeSpan({"http.target": "/api/v1/entries"})
    _scrub_span_query_string(span, _scope("/api/v1/entries", b""))
    assert span.attributes["http.target"] == "/api/v1/entries"


def test_a_missing_target_is_filled_in_scrubbed() -> None:
    """Some semconv versions leave http.target unset; the path must still not carry
    the query if the instrumentation later derives one."""
    span = _FakeSpan({})
    _scrub_span_query_string(span, _scope("/api/v1/entries", b"q=secret"))
    assert span.attributes["http.target"] == "/api/v1/entries?[scrubbed]"


def test_a_span_that_is_not_recording_is_left_alone() -> None:
    span = _FakeSpan({"http.target": "/x?q=1"}, recording=False)
    _scrub_span_query_string(span, _scope("/x", b"q=1"))
    assert span.attributes["http.target"] == "/x?q=1"


def test_no_span_does_not_raise() -> None:
    _scrub_span_query_string(None, _scope("/x", b"q=1"))
