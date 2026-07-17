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

from app import telemetry
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
    refresher = asyncio.create_task(_gauge_refresh_loop()) if telemetry.is_enabled() else None
    try:
        yield
    finally:
        if refresher is not None:
            refresher.cancel()
            with suppress(asyncio.CancelledError):
                await refresher
        telemetry.shutdown()


app = FastAPI(title="alo-reader", version="0.0.0", lifespan=lifespan)
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

api_v1 = APIRouter(prefix="/api/v1")


@api_v1.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


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
