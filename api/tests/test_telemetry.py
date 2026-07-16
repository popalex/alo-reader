"""app.telemetry: disabled is a safe no-op, and the metric helpers drive their
instruments. The real ``configure_telemetry`` wiring (which instruments httpx/logging
globally) is exercised out of band, not here, to keep the suite isolated.
"""

from unittest.mock import MagicMock

import pytest

from app import telemetry
from app.telemetry import TelemetryRuntime, _Gauges


@pytest.fixture(autouse=True)
def _reset_runtime():
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
