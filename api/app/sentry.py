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

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # the SDK is imported lazily in configure_sentry
    from sentry_sdk.types import Event, Hint

log = logging.getLogger("alo.sentry")

_enabled = False


def _scrub_query_string(event: Event, _hint: Hint) -> Event:
    """Drop the request's query string before the event leaves the process.

    data_collection drops query_string as well; this is the backstop, and it also
    covers the url field. Before data_collection, send_default_pii=False let it
    through (sentry-sdk 2.69.1: a 500 on /streams/all/entries?q=... arrived with
    query_string='q=my+private+search+terms'). Search terms are the most personal
    thing this API takes in a URL, and none of it helps group an error.
    """
    request: Any = event.get("request")
    if isinstance(request, dict):
        if request.get("query_string"):
            request["query_string"] = "[scrubbed]"
        url = request.get("url")
        if isinstance(url, str) and "?" in url:
            request["url"] = url.split("?", 1)[0]
    return event


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
        # What the SDK may attach to an event. Feed URLs, article contents, search terms
        # and auth headers are not error context. This replaces send_default_pii, which
        # 2.73 deprecates and which never covered all of that: with it off, a failing
        # POST still carried its JSON body (a subscribe call's feed URL) and the local
        # variables of every frame. Setting this also turns off the SDK's EventScrubber,
        # so the header denylist takes over its job; its terms are the ones
        # send_default_pii=False used.
        data_collection={
            "user_info": False,
            "cookies": {"mode": "off"},
            "http_headers": {
                "request": {
                    "mode": "denylist",
                    "terms": ["forwarded", "-ip", "remote-", "via", "-user"],
                }
            },
            "http_bodies": [],
            "url_query_params": {"mode": "off"},
            "stack_frame_variables": False,
            "database_query_data": False,
            "queues": False,
            "graphql": {"document": False, "variables": False},
            "gen_ai": {"inputs": False, "outputs": False},
        },
        # INFO and above become breadcrumbs (the trail leading to an error); only
        # ERROR and above become events. Without this bound, every warning the poller
        # emits for an unreachable feed would be an alert.
        integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
        # Which process an event came from. api and worker fail in different ways.
        server_name=service_name,
        # Two hooks for one job. before_send only sees error events; a transaction
        # (sent whenever traces_sample_rate is above 0) goes through
        # before_send_transaction instead, and carries the same request block.
        before_send=_scrub_query_string,
        before_send_transaction=_scrub_query_string,
    )
    sentry_sdk.set_tag("service", service_name)

    _enabled = True
    # Deliberately not logged here. In the API this runs at import, before uvicorn has
    # installed its logging config, so the line would be dropped; each caller announces
    # it at a point where logging is actually working.
    return True
