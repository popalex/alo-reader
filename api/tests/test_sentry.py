"""Sentry is optional, and parallel to OpenTelemetry.

The parallel part is the half worth testing. Sentry and OTel both hook the logging
system, and the failure everyone hits is one of them quietly taking the other's place:
errors reach Sentry and the logs stop reaching Loki, or the reverse, and nobody notices
until an incident. So these assert both handlers survive each other.
"""

import logging
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from app import sentry
from app.config import Settings


@pytest.fixture(autouse=True)
def _reset_sentry() -> Iterator[None]:
    """configure_sentry is process-global and latches; unlatch between tests."""
    sentry._enabled = False
    yield
    sentry._enabled = False


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Settings with a DSN, without needing the environment or a database."""

    def _make(**overrides: Any) -> Settings:
        values = {"database_url": "postgresql+asyncpg://x:y@localhost/z", **overrides}
        built = Settings(**values)
        monkeypatch.setattr("app.config.get_settings", lambda: built)
        return built

    return _make


def test_off_without_a_dsn(settings: Callable[..., Settings]) -> None:
    settings(sentry_dsn="")
    assert sentry.configure_sentry(service_name="alo-api", version="1.0.0") is False
    assert sentry.is_enabled() is False


def test_blank_dsn_counts_as_off(settings: Callable[..., Settings]) -> None:
    settings(sentry_dsn="   ")
    assert sentry.configure_sentry(service_name="alo-api", version="1.0.0") is False


def test_init_options(settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch) -> None:
    """The defaults that matter are privacy and not competing with OTel for traces."""
    captured: dict[str, Any] = {}
    import sentry_sdk

    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: captured.update(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a: None)

    settings(sentry_dsn="https://key@example.invalid/1", sentry_environment="staging")
    assert sentry.configure_sentry(service_name="alo-worker", version="1.2.3") is True

    assert captured["dsn"] == "https://key@example.invalid/1"
    assert captured["release"] == "1.2.3"
    assert captured["environment"] == "staging"
    assert captured["server_name"] == "alo-worker"
    # Sentry must not start tracing: Tempo owns traces, and two tracing systems in one
    # process double-instrument every request.
    assert captured["traces_sample_rate"] == 0.0
    # Feed URLs, article bodies and auth headers are not error context.
    assert captured["send_default_pii"] is False


def test_empty_environment_becomes_none(
    settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unset SENTRY_ENVIRONMENT must not tag every event with the empty string."""
    captured: dict[str, Any] = {}
    import sentry_sdk

    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: captured.update(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a: None)

    settings(sentry_dsn="https://key@example.invalid/1", sentry_environment="")
    sentry.configure_sentry(service_name="alo-api", version="1.0.0")
    assert captured["environment"] is None


def test_configure_is_idempotent(
    settings: Callable[..., Settings], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []
    import sentry_sdk

    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a: None)

    settings(sentry_dsn="https://key@example.invalid/1")
    assert sentry.configure_sentry(service_name="alo-api", version="1.0.0") is True
    assert sentry.configure_sentry(service_name="alo-api", version="1.0.0") is True
    assert len(calls) == 1


def test_sentry_leaves_an_existing_log_handler_attached(settings: Callable[..., Settings]) -> None:
    """The OTLP handler must survive Sentry's init.

    Stands in for telemetry.enable_log_export(), which attaches a handler to the api
    and worker loggers. If Sentry's logging integration replaced handlers instead of
    adding one, Loki would go silent the day someone set a DSN.
    """
    target = logging.getLogger("alo.api")
    sentinel = logging.NullHandler()
    target.addHandler(sentinel)
    try:
        settings(sentry_dsn="https://key@example.invalid/1")
        sentry.configure_sentry(service_name="alo-api", version="1.0.0")
        assert sentinel in target.handlers, "Sentry init detached an existing log handler"
    finally:
        target.removeHandler(sentinel)
        import sentry_sdk

        sentry_sdk.init(dsn="")  # tear the real client back down


def test_records_still_reach_other_handlers_after_init(settings: Callable[..., Settings]) -> None:
    """Not just attached: still receiving records."""
    seen: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(record.getMessage())

    target = logging.getLogger("alo.api")
    handler = Capture()
    target.addHandler(handler)
    try:
        settings(sentry_dsn="https://key@example.invalid/1")
        sentry.configure_sentry(service_name="alo-api", version="1.0.0")
        target.error("still_shipping_to_loki")
        assert "still_shipping_to_loki" in seen
    finally:
        target.removeHandler(handler)
        import sentry_sdk

        sentry_sdk.init(dsn="")


def test_query_string_never_leaves_the_process() -> None:
    # send_default_pii=False does not cover the query string: verified against
    # sentry-sdk 2.69.1, a 500 on /streams/all/entries?q=... arrives carrying
    # query_string='q=my+private+search+terms'. Search terms are the most personal
    # thing this API takes in a URL.
    event: Any = {
        "request": {
            "url": "https://reader.example/api/v1/streams/all/entries?q=private+terms",
            "query_string": "q=private+terms&status=all",
        }
    }

    scrubbed = sentry._scrub_query_string(event, {})

    assert scrubbed["request"]["query_string"] == "[scrubbed]"
    assert scrubbed["request"]["url"] == "https://reader.example/api/v1/streams/all/entries"
