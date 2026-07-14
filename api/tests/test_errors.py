"""Unhandled errors keep the uniform envelope (never leak internals), and every
response carries a correlatable X-Request-ID (M7)."""

import httpx
import pytest
from fastapi import FastAPI

from app.errors import register_exception_handlers


async def test_unhandled_exception_returns_envelope_without_leaking() -> None:
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internal detail")

    # raise_app_exceptions=False: the handler's response is what the client sees even
    # though Starlette re-raises for server-side logging.
    transport = httpx.ASGITransport(app=test_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal"
    assert "secret internal detail" not in resp.text  # no leak
    assert "Traceback" not in resp.text


async def test_request_id_is_assigned_and_echoed(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.get("/api/v1/healthz")
    assert resp.headers.get("x-request-id")  # generated when absent


@pytest.mark.parametrize("rid", ["abc-123"])
async def test_request_id_is_propagated(api_client: httpx.AsyncClient, rid: str) -> None:
    resp = await api_client.get("/api/v1/healthz", headers={"X-Request-ID": rid})
    assert resp.headers.get("x-request-id") == rid
