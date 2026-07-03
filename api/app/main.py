"""FastAPI application entrypoint.

Serves the API under the ``/api/v1`` prefix. Caddy reverse-proxies ``/api/*`` to
this app without stripping the prefix, so the app owns the full path.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.auth import AuthMiddleware
from app.auth import router as auth_router
from app.config import validate_boot_config
from app.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    validate_boot_config()
    yield


app = FastAPI(title="alo-reader", version="0.0.0", lifespan=lifespan)
register_exception_handlers(app)
app.add_middleware(AuthMiddleware)

api_v1 = APIRouter(prefix="/api/v1")


@api_v1.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


api_v1.include_router(auth_router)
app.include_router(api_v1)
