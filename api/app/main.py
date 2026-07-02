"""FastAPI application entrypoint.

Serves the API under the ``/api/v1`` prefix. Caddy reverse-proxies ``/api/*`` to
this app without stripping the prefix, so the app owns the full path.
"""

from fastapi import APIRouter, FastAPI

app = FastAPI(title="alo-reader", version="0.0.0")

api_v1 = APIRouter(prefix="/api/v1")


@api_v1.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(api_v1)
