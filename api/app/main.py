"""FastAPI application entrypoint.

Serves the API under the ``/api/v1`` prefix. Caddy reverse-proxies ``/api/*`` to
this app without stripping the prefix, so the app owns the full path.
"""

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, FastAPI

from app import sentry, telemetry
from app.auth import AuthMiddleware
from app.auth import router as auth_router
from app.config import get_settings, validate_boot_config
from app.db import get_engine, get_sessionmaker
from app.errors import register_exception_handlers
from app.log import RequestContextMiddleware
from app.routes.counts import router as counts_router
from app.routes.discover import router as discover_router
from app.routes.entries import router as entries_router
from app.routes.folders import router as folders_router
from app.routes.icons import router as icons_router
from app.routes.opml import router as opml_router
from app.routes.streams import router as streams_router
from app.routes.subscriptions import router as subscriptions_router
from app.security import SecurityHeadersMiddleware
from app.version import APP_VERSION

# The API process had no logging configuration at all: uvicorn configures its own
# uvicorn.* loggers and leaves root at WARNING with no handlers, so every INFO line the
# app logged went nowhere and WARNING/ERROR only escaped through logging's lastResort
# fallback, unformatted. basicConfig here mirrors what the worker already does at its
# own import. It does not fight uvicorn (whose loggers do not propagate) and it does not
# replace the OTLP handler, which telemetry.enable_log_export() attaches in the lifespan:
# stdout and Loki both get the records.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

log = logging.getLogger("alo.api")

# How often the SQL-derived gauges (worker lag, table/db sizes) are refreshed into
# the telemetry cache the OTel ObservableGauge callbacks read.
_GAUGE_REFRESH_S = 15.0


async def _gauge_refresh_loop() -> None:
    """Periodically read the DB-derived gauges and push them into the telemetry cache."""
    from app.store import metrics as metrics_store

    while True:
        try:
            async with get_sessionmaker()() as session:
                lag = await metrics_store.worker_lag_seconds(session)
                sizes = await metrics_store.table_sizes(session)
                db_bytes = await metrics_store.db_size_bytes(session)
            telemetry.set_gauges(
                lag_seconds=lag,
                db_bytes=db_bytes,
                table_bytes={t.table: t.bytes for t in sizes},
                table_rows={t.table: t.rows for t in sizes},
            )
        except Exception:  # noqa: BLE001 — a gauge blip must not kill the loop
            log.exception("gauge_refresh_failed")
        await asyncio.sleep(_GAUGE_REFRESH_S)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    validate_boot_config()
    # Telemetry is configured at import (below), not here: instrumenting in the lifespan
    # is too late — Starlette builds the middleware stack on the first ASGI call, so the
    # FastAPI server-span middleware would never be installed and browser traces couldn't
    # continue into the backend. Here we only start the gauge refresher + flush on exit.
    # Attach the OTLP log handler now, not at import: uvicorn has finished installing its
    # own logging config by the time the lifespan runs, so the handler survives on the
    # uvicorn.* loggers and the api's logs actually reach Loki.
    if telemetry.is_enabled():
        telemetry.enable_log_export()
    # Sentry is initialised at import (below), but anything it logged there went
    # nowhere: uvicorn installs its logging config after the module is imported, so an
    # INFO line at import time is dropped. Say it here instead, where it is visible,
    # because "is error reporting actually on?" is a question operators ask.
    if sentry.is_enabled():
        log.info("sentry_enabled service=alo-api release=%s", APP_VERSION)
    refresher = asyncio.create_task(_gauge_refresh_loop()) if telemetry.is_enabled() else None
    try:
        yield
    finally:
        if refresher is not None:
            refresher.cancel()
            with suppress(asyncio.CancelledError):
                await refresher
        telemetry.shutdown()


app = FastAPI(title="alo-reader", version=APP_VERSION, lifespan=lifespan)
register_exception_handlers(app)
app.add_middleware(AuthMiddleware)
# Added last → outermost: security headers land on every response, including the
# auth middleware's 401/429 and error envelopes. The request-context middleware is
# outer of that so its X-Request-ID is set before anything runs and echoed on every
# response.
app.add_middleware(SecurityHeadersMiddleware)
# Outermost: assign the X-Request-ID before anything runs, echo it on every response.
app.add_middleware(RequestContextMiddleware)

# Configure telemetry at import — before the ASGI/middleware stack is built on the first
# request — so FastAPIInstrumentor's server span exists and continues the browser's
# traceparent. Gated on the raw env var (not Settings, which needs DATABASE_URL) so
# importing the app for tests / the openapi dump never constructs settings or the engine.
if os.getenv("OTEL_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
    telemetry.configure_telemetry(
        service_name=get_settings().otel_service_name,
        version=app.version,
        app=app,
        engine=get_engine(),
    )

# Sentry, independently of the above: either, both, or neither can be on. Gated on the
# raw env var for the same reason telemetry is -- importing the app for a test or the
# openapi dump must not construct Settings, which requires DATABASE_URL.
if os.getenv("SENTRY_DSN", "").strip():
    sentry.configure_sentry(service_name="alo-api", version=app.version)

api_v1 = APIRouter(prefix="/api/v1")


@api_v1.get("/healthz")
async def healthz() -> dict[str, str]:
    # version answers "which build is this?" from the outside, without shelling into
    # the container. Deliberately still DB-free and auth-free: it is a liveness probe
    # (deploy/docker-compose.yml) before it is anything else.
    return {"status": "ok", "version": APP_VERSION}


api_v1.include_router(auth_router)
api_v1.include_router(folders_router)
api_v1.include_router(subscriptions_router)
api_v1.include_router(streams_router)
api_v1.include_router(entries_router)
api_v1.include_router(counts_router)
api_v1.include_router(discover_router)
api_v1.include_router(opml_router)
api_v1.include_router(icons_router)
app.include_router(api_v1)
