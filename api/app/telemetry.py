"""OpenTelemetry bootstrap + small instrumentation helpers (traces, metrics, logs).

OTel is optional: the default image/test env does not install the ``otel`` extra, so
this module imports OpenTelemetry lazily and every public helper is a safe no-op when
telemetry is disabled. ``configure_telemetry`` is called once per process (API lifespan
and the worker's ``run``) and wires the three signals to the OTLP endpoint from
``OTEL_EXPORTER_OTLP_*`` env. Domain metrics replace the old hand-rolled ``/metrics``.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("alo.telemetry")

# Parse the operation + table from a SQL statement so DB spans read "SELECT feeds"
# instead of a bare "SELECT" (the SQLAlchemy instrumentation names by operation only).
# The \b(?!\s*\() after the table name skips a "FROM func(" match, so the FROM inside
# an expression like EXTRACT(EPOCH FROM now()) is ignored and the real table FROM wins.
_DB_NAME_RES = (
    re.compile(r"(?is)^\s*(select)\b.*?\bfrom\s+\"?(\w+)\b(?!\s*\()"),
    re.compile(r"(?is)^\s*(insert)\s+into\s+\"?(\w+)"),
    re.compile(r"(?is)^\s*(update)\s+\"?(\w+)"),
    re.compile(r"(?is)^\s*(delete)\b.*?\bfrom\s+\"?(\w+)\b(?!\s*\()"),
)


def _db_span_name(statement: str) -> str | None:
    for pattern in _DB_NAME_RES:
        m = pattern.match(statement)
        if m:
            return f"{m.group(1).upper()} {m.group(2)}"
    return None


# Loggers whose records we ship to Loki via OTLP. uvicorn's loggers set
# propagate=False, so the handler must be attached to them directly.
_LOG_EXPORT_LOGGERS = ("alo.api", "worker", "uvicorn", "uvicorn.error", "uvicorn.access")


class _HealthLogFilter(logging.Filter):
    """Drop /healthz access logs so probes don't flood Loki (uvicorn.access format:
    request path is ``record.args[2]``)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            if args[2].startswith("/api/v1/healthz"):
                return False
        return True


@dataclass
class _Gauges:
    """Latest values for the SQL-derived gauges, refreshed by a periodic task and read
    (synchronously) by the OTel ObservableGauge callbacks."""

    lag_seconds: float = 0.0
    db_bytes: int = 0
    table_bytes: dict[str, int] = field(default_factory=dict)
    table_rows: dict[str, int] = field(default_factory=dict)


@dataclass
class TelemetryRuntime:
    enabled: bool = False
    tracer_provider: Any = None
    meter_provider: Any = None
    logger_provider: Any = None
    tracer: Any = None
    # Domain metric instruments.
    fetch_outcomes: Any = None
    fetch_host_responses: Any = None
    fetch_duration: Any = None
    entries_inserted: Any = None
    gauges: _Gauges = field(default_factory=_Gauges)
    _log_handler: Any = None

    def shutdown(self) -> None:
        if not self.enabled:
            return
        if self._log_handler is not None:
            for name in _LOG_EXPORT_LOGGERS:
                logging.getLogger(name).removeHandler(self._log_handler)
            self._log_handler = None
        for provider in (self.tracer_provider, self.meter_provider, self.logger_provider):
            if provider is not None:
                try:
                    provider.shutdown()
                except Exception:  # noqa: BLE001 — best-effort flush on shutdown
                    logger.exception("failed to shut down an OpenTelemetry provider")


_runtime = TelemetryRuntime()


def _exporter_classes(protocol: str) -> tuple[Any, Any, Any]:
    # Resolve the grpc/http exporter variants dynamically: importing the same class
    # names conditionally binds different types to one name, which the typechecker
    # rejects — importlib sidesteps that entirely.
    import importlib

    base = "opentelemetry.exporter.otlp.proto." + (
        "http" if protocol == "http/protobuf" else "grpc"
    )
    span = importlib.import_module(f"{base}.trace_exporter").OTLPSpanExporter
    metric = importlib.import_module(f"{base}.metric_exporter").OTLPMetricExporter
    log = importlib.import_module(f"{base}._log_exporter").OTLPLogExporter
    return span, metric, log


def _name_httpx_span(span: Any, request: Any) -> None:
    """Rename the httpx auto-span from bare ``GET`` to ``GET <host>`` so the feed
    fetches read clearly in Tempo. Low-cardinality (host only, not full URL)."""
    if span is None or not span.is_recording():
        return
    try:
        host = getattr(request.url, "host", None)
        if isinstance(host, (bytes, bytearray)):
            host = host.decode("ascii", "ignore")
        method = request.method
        if isinstance(method, (bytes, bytearray)):
            method = method.decode("ascii", "ignore")
        if method and host:
            span.update_name(f"{method} {host}")
    except Exception:  # noqa: BLE001 — a naming hook must never break a request
        pass


def configure_telemetry(
    *, service_name: str, version: str = "0.0.0", app: Any = None, engine: Any = None
) -> TelemetryRuntime:
    """Wire traces + metrics + logs for this process. No-op if OTel is disabled; raises
    only if enabled without the extra installed. ``app`` (FastAPI) enables server
    instrumentation; ``engine`` (async SQLAlchemy) enables DB spans."""
    global _runtime
    from app.config import get_settings

    if not get_settings().otel_enabled or _runtime.enabled:
        return _runtime

    try:
        from opentelemetry import metrics, trace
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        raise RuntimeError(
            "OTEL_ENABLED is true but this process was not installed with its 'otel' extra"
        ) from exc

    protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").strip().lower()
    if protocol not in {"grpc", "http/protobuf"}:
        raise RuntimeError(f"unsupported OTEL_EXPORTER_OTLP_PROTOCOL: {protocol}")
    SpanExporter, MetricExporter, LogExporter = _exporter_classes(protocol)

    resource = Resource.create({"service.name": service_name, "service.version": version})

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(SpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource, metric_readers=[PeriodicExportingMetricReader(MetricExporter())]
    )
    metrics.set_meter_provider(meter_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(LogExporter()))
    set_logger_provider(logger_provider)

    # Auto-instrumentation. FastAPI only in the API process; httpx + SQLAlchemy in both.
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
            excluded_urls="healthz",
        )
    HTTPXClientInstrumentor().instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        request_hook=_name_httpx_span,
    )
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(
            engine=engine.sync_engine,
            tracer_provider=tracer_provider,
            meter_provider=meter_provider,
        )
        # Rename DB spans "<op> <table>" (e.g. SELECT feeds). Registered after the
        # instrumentation's own before_cursor_execute, which stashes the span it just
        # created on the execution context (context._otel_span) — the span is NOT the
        # current one (it's attached only inside a `with use_span` block), so we reach
        # it through the context and retitle it before it's exported.
        from sqlalchemy import event as sa_event

        def _rename_db_span(
            conn: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            try:
                span = getattr(context, "_otel_span", None)
                if span is not None and span.is_recording():
                    name = _db_span_name(statement)
                    if name:
                        span.update_name(name)
            except Exception:  # noqa: BLE001 — a naming hook must never break a query
                pass

        sa_event.listen(engine.sync_engine, "before_cursor_execute", _rename_db_span)

    # Route the app + uvicorn logger tree to Loki, trace-id stamped.
    LoggingInstrumentor().instrument(tracer_provider=tracer_provider, inject_trace_context=True)
    log_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    log_handler.addFilter(_HealthLogFilter())
    for name in _LOG_EXPORT_LOGGERS:
        logging.getLogger(name).addHandler(log_handler)

    meter = meter_provider.get_meter(service_name)
    gauges = _Gauges()
    _register_observable_gauges(meter, gauges)

    _runtime = TelemetryRuntime(
        enabled=True,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        tracer=tracer_provider.get_tracer(service_name),
        fetch_outcomes=meter.create_counter(
            "alo.fetch.outcomes", unit="{fetch}", description="Feed fetches by outcome class"
        ),
        fetch_host_responses=meter.create_counter(
            "alo.fetch.host_responses", unit="{response}", description="Per-host 403/429 responses"
        ),
        fetch_duration=meter.create_histogram(
            "alo.fetch.duration", unit="ms", description="Feed fetch+persist wall-clock duration"
        ),
        entries_inserted=meter.create_counter(
            "alo.entries.inserted", unit="{entry}", description="New entries inserted by the worker"
        ),
        gauges=gauges,
        _log_handler=log_handler,
    )
    logger.info("OpenTelemetry enabled: service=%s protocol=%s", service_name, protocol)
    return _runtime


def _register_observable_gauges(meter: Any, gauges: _Gauges) -> None:
    """SQL-derived gauges: callbacks read the cache the refresher task updates."""
    from opentelemetry.metrics import CallbackOptions, Observation

    def lag(_o: CallbackOptions) -> list[Observation]:
        return [Observation(gauges.lag_seconds)]

    def db_bytes(_o: CallbackOptions) -> list[Observation]:
        return [Observation(gauges.db_bytes)]

    def table_bytes(_o: CallbackOptions) -> list[Observation]:
        return [Observation(v, {"table": t}) for t, v in gauges.table_bytes.items()]

    def table_rows(_o: CallbackOptions) -> list[Observation]:
        return [Observation(v, {"table": t}) for t, v in gauges.table_rows.items()]

    meter.create_observable_gauge("alo.worker.lag_seconds", callbacks=[lag], unit="s")
    meter.create_observable_gauge("alo.db.bytes", callbacks=[db_bytes], unit="By")
    meter.create_observable_gauge("alo.table.bytes", callbacks=[table_bytes], unit="By")
    meter.create_observable_gauge("alo.table.rows", callbacks=[table_rows], unit="{row}")


# ── Public helpers (all no-op when disabled) ─────────────────────────────────


def is_enabled() -> bool:
    return _runtime.enabled


def shutdown() -> None:
    _runtime.shutdown()


def record_fetch(*, outcome: str, http_status: int | None, host: str, duration_ms: float) -> None:
    r = _runtime
    if not r.enabled:
        return
    r.fetch_outcomes.add(1, {"class": outcome})
    r.fetch_duration.record(duration_ms, {"class": outcome})
    if http_status in (403, 429):
        r.fetch_host_responses.add(1, {"host": host or "?", "code": str(http_status)})


def record_entries_inserted(count: int) -> None:
    if _runtime.enabled and count:
        _runtime.entries_inserted.add(count)


def set_gauges(
    *, lag_seconds: float, db_bytes: int, table_bytes: dict[str, int], table_rows: dict[str, int]
) -> None:
    g = _runtime.gauges
    g.lag_seconds = lag_seconds
    g.db_bytes = db_bytes
    g.table_bytes = table_bytes
    g.table_rows = table_rows


def current_traceparent() -> str | None:
    """The active span's W3C traceparent, or None. Stored when a request queues async
    work so the worker can continue the same trace on the resulting poll."""
    if not _runtime.enabled:
        return None
    from opentelemetry.propagate import inject

    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier.get("traceparent")


def _context_from_traceparent(traceparent: str | None) -> Any:
    if not traceparent:
        return None
    from opentelemetry.propagate import extract

    return extract({"traceparent": traceparent})


@contextmanager
def start_span(
    name: str,
    *,
    attributes: dict[str, Any] | None = None,
    parent_traceparent: str | None = None,
) -> Iterator[Any | None]:
    """Start a manual span (no-op when disabled). ``parent_traceparent`` continues a
    trace propagated from another process (e.g. the request that queued this work)."""
    if not _runtime.enabled:
        yield None
        return
    attrs = {k: v for k, v in (attributes or {}).items() if v is not None}
    with _runtime.tracer.start_as_current_span(
        name,
        context=_context_from_traceparent(parent_traceparent),
        attributes=attrs,
        record_exception=True,
        set_status_on_exception=True,
    ) as span:
        yield span
