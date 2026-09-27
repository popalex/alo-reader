"""app.telemetry: disabled is a safe no-op, and the metric helpers drive their
instruments. The real ``configure_telemetry`` wiring (which instruments httpx/logging
globally) is exercised out of band, not here, to keep the suite isolated.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest

from app import telemetry
from app.telemetry import TelemetryRuntime, _Gauges


@pytest.fixture(autouse=True)
def _reset_runtime() -> Iterator[None]:
    """Isolate the module-global runtime around each test."""
    saved = telemetry._runtime
    telemetry._runtime = TelemetryRuntime()
    yield
    telemetry._runtime = saved


def test_disabled_helpers_are_noops() -> None:
    assert telemetry.is_enabled() is False
    # None of these raise, and start_span yields None when disabled.
    telemetry.record_fetch(outcome="new_body", http_status=200, host="ex.com", duration_ms=1.0)
    telemetry.record_entries_inserted(5)
    with telemetry.start_span("x", attributes={"k": "v"}) as span:
        assert span is None
    telemetry.shutdown()


def test_record_fetch_drives_instruments() -> None:
    rt = TelemetryRuntime(
        enabled=True,
        fetch_outcomes=MagicMock(),
        fetch_host_responses=MagicMock(),
        fetch_duration=MagicMock(),
        entries_inserted=MagicMock(),
        gauges=_Gauges(),
    )
    telemetry._runtime = rt

    telemetry.record_fetch(
        outcome="http_error", http_status=429, host="a.example", duration_ms=12.0
    )
    rt.fetch_outcomes.add.assert_called_once_with(1, {"class": "http_error"})
    rt.fetch_duration.record.assert_called_once_with(12.0, {"class": "http_error"})
    rt.fetch_host_responses.add.assert_called_once_with(1, {"host": "a.example", "code": "429"})

    # A 2xx doesn't touch the per-host 403/429 counter.
    rt.fetch_host_responses.reset_mock()
    telemetry.record_fetch(outcome="new_body", http_status=200, host="a.example", duration_ms=3.0)
    rt.fetch_host_responses.add.assert_not_called()

    telemetry.record_entries_inserted(7)
    rt.entries_inserted.add.assert_called_once_with(7)
    telemetry.record_entries_inserted(0)  # zero is skipped
    rt.entries_inserted.add.assert_called_once()


def test_set_gauges_updates_cache() -> None:
    rt = TelemetryRuntime(enabled=True, gauges=_Gauges())
    telemetry._runtime = rt
    telemetry.set_gauges(
        lag_seconds=4.5, db_bytes=1000, table_bytes={"entries": 900}, table_rows={"entries": 12}
    )
    assert rt.gauges.lag_seconds == 4.5
    assert rt.gauges.db_bytes == 1000
    assert rt.gauges.table_bytes == {"entries": 900}
    assert rt.gauges.table_rows == {"entries": 12}


def test_db_span_name_parses_op_and_table() -> None:
    from app.telemetry import _db_span_name

    assert _db_span_name("SELECT feeds.id FROM feeds WHERE id = 1") == "SELECT feeds"
    assert _db_span_name('INSERT INTO "entries" (id) VALUES (1)') == "INSERT entries"
    assert _db_span_name("UPDATE feeds SET title='x' WHERE id=1") == "UPDATE feeds"
    assert _db_span_name("DELETE FROM subscriptions WHERE id=1") == "DELETE subscriptions"
    assert _db_span_name("BEGIN") is None
    # A FROM inside a function expression (EXTRACT(... FROM ...)) must not be mistaken
    # for the table — the real "FROM feeds" wins.
    assert (
        _db_span_name(
            "SELECT COALESCE(EXTRACT(EPOCH FROM now() - min(next_check_at)), 0) "
            "FROM feeds WHERE next_check_at <= now()"
        )
        == "SELECT feeds"
    )
    assert _db_span_name("SELECT pg_database_size(current_database())") is None


def test_shutdown_leaves_is_enabled_honest() -> None:
    # Every record helper checks is_enabled() before touching a provider, and
    # configure_telemetry returns early while it is true. Leaving it set after
    # shutdown means emits go to dead providers and the process cannot re-arm.
    runtime = telemetry.TelemetryRuntime(enabled=True)
    runtime.shutdown()
    assert runtime.enabled is False


def test_prime_worker_counters_starts_every_series_at_zero() -> None:
    rt = TelemetryRuntime(
        enabled=True, fetch_outcomes=MagicMock(), entries_inserted=MagicMock(), gauges=_Gauges()
    )
    telemetry._runtime = rt

    telemetry.prime_worker_counters(("new_body", "not_modified"))

    assert rt.fetch_outcomes.add.call_args_list == [
        ((0, {"class": "new_body"}),),
        ((0, {"class": "not_modified"}),),
    ]
    rt.entries_inserted.add.assert_called_once_with(0)


def test_prime_worker_counters_is_a_noop_when_disabled() -> None:
    telemetry.prime_worker_counters(("new_body",))  # must not touch the None instruments


def test_outcome_classes_cover_every_status_the_worker_records() -> None:
    """A status missing from OUTCOME_CLASSES gets no zero sample, and its first
    fetch after a restart disappears from the rate panel again. Reads the literals
    out of the source so a new status cannot be added without this noticing."""
    import re
    from pathlib import Path
    from typing import get_args

    from app.worker import fetch, pipeline

    source = Path(pipeline.__file__).read_text()
    in_pipeline = set(re.findall(r'status="([a-z_]+)"', source))
    assert in_pipeline, "the pattern no longer matches; update this test"
    recorded = in_pipeline | set(get_args(fetch.FetchStatus))
    assert recorded <= set(pipeline.OUTCOME_CLASSES)
