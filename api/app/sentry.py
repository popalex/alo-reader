"""Optional Sentry error reporting, running alongside OpenTelemetry.

Off unless ``SENTRY_DSN`` is set. Unlike :mod:`app.telemetry`, the SDK is a base
dependency rather than an extra, so turning this on is one environment variable and
not an image rebuild.

**This is parallel to OTel, not a replacement.** OpenTelemetry keeps owning traces,
metrics, and log export to Loki; Sentry only groups and alerts on errors. Two
consequences are wired in deliberately below:

- ``traces_sample_rate`` defaults to 0, so the SDK installs no tracing of its own.
  Sentry 2.x can take over span handling when tracing is on, and running two tracing
  systems in one process means double instrumentation and two bills for the same
  spans. Tempo is the trace store.
- The logging integration only *reads* records to build breadcrumbs and error events.
  It adds its own handler and removes nobody else's, so the OTLP handler that
  ``telemetry.enable_log_export()`` attaches keeps shipping every line to Loki.
"""

import logging

log = logging.getLogger("alo.sentry")

_enabled = False


def is_enabled() -> bool:
    return _enabled


def configure_sentry(*, service_name: str, version: str) -> bool:
    """Initialise Sentry if a DSN is configured. Returns whether it is on.

    Safe to call more than once; the second call is a no-op.
    """
    global _enabled
    from app.config import get_settings

    if _enabled:
        return True

    settings = get_settings()
    dsn = settings.sentry_dsn.strip()
    if not dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=dsn,
        release=version,
        environment=settings.sentry_environment.strip() or None,
        # See the module docstring: 0 keeps Sentry out of the tracing business.
        traces_sample_rate=settings.sentry_traces_sample_rate,
        # The SDK's default, set explicitly because it is a privacy decision and not a
        # detail: feed URLs, article contents and auth headers are not error context.
        # With this off the SDK sends no request bodies, cookies or user identifiers.
        send_default_pii=False,
        # INFO and above become breadcrumbs (the trail leading to an error); only
        # ERROR and above become events. Without this bound, every warning the poller
        # emits for an unreachable feed would be an alert.
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
        # Which process an event came from. api and worker fail in different ways.
        server_name=service_name,
    )
    sentry_sdk.set_tag("service", service_name)

    _enabled = True
    # Deliberately not logged here. In the API this runs at import, before uvicorn has
    # installed its logging config, so the line would be dropped; each caller announces
    # it at a point where logging is actually working.
    return True
