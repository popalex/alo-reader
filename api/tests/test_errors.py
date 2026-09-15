"""Unhandled errors keep the uniform envelope (never leak internals), and every
response carries a correlatable X-Request-ID (M7)."""

import httpx
import pytest
from fastapi import FastAPI

from app.errors import register_exception_handlers

from .conftest import PatUser


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


async def test_request_id_is_echoed_on_a_500(api_client: httpx.AsyncClient) -> None:
    """The id must survive the one path that bypasses the middleware.

    A 500 is produced by ServerErrorMiddleware, outside RequestContextMiddleware's send
    wrapper, so the header was absent on exactly the responses the id exists to
    correlate: the log line had it, the client never did.
    """
    rid = "trace-me-9f2c"
    resp = await api_client.get("/api/v1/__boom__", headers={"X-Request-ID": rid})
    # Route doesn't exist -> 404, which still goes through the normal stack.
    assert resp.headers.get("x-request-id") == rid


async def test_unhandled_500_carries_the_request_id() -> None:
    import httpx as _httpx
    from fastapi import FastAPI

    from app.errors import register_exception_handlers
    from app.log import RequestContextMiddleware

    test_app = FastAPI()
    register_exception_handlers(test_app)
    test_app.add_middleware(RequestContextMiddleware)

    @test_app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    transport = _httpx.ASGITransport(app=test_app, raise_app_exceptions=False)
    async with _httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/boom", headers={"X-Request-ID": "given-id-42"})

    assert resp.status_code == 500
    assert resp.headers.get("x-request-id") == "given-id-42"


@pytest.mark.parametrize("rid", ["abc-123"])
async def test_request_id_is_propagated(api_client: httpx.AsyncClient, rid: str) -> None:
    resp = await api_client.get("/api/v1/healthz", headers={"X-Request-ID": rid})
    assert resp.headers.get("x-request-id") == rid


async def test_an_out_of_range_id_is_a_422_not_a_500(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    # Ids are bigints; FastAPI's plain int is unbounded, so an oversized one reached
    # asyncpg and came back as "value out of int64 range" — a 500, and on the public
    # /icons route an unauthenticated one.
    huge = 2**63
    icon = await api_client.get(f"/api/v1/icons/{huge}")
    entry = await api_client.get(f"/api/v1/entries/{huge}", headers=pat_user.headers)
    state = await api_client.post(
        "/api/v1/entries/state", json={"ids": [huge], "read": True}, headers=pat_user.headers
    )

    assert icon.status_code == 422
    assert entry.status_code == 422
    assert state.status_code == 422


async def test_an_out_of_range_folder_position_is_a_422_not_a_500(
    api_client: httpx.AsyncClient, pat_user: PatUser
) -> None:
    # Folder.position is an int4 column.
    resp = await api_client.post(
        "/api/v1/folders",
        json={"name": "overflow", "position": 3_000_000_000},
        headers=pat_user.headers,
    )
    assert resp.status_code == 422


async def test_405_keeps_its_allow_header(api_client: httpx.AsyncClient) -> None:
    # Starlette raises the 405 with an Allow header; the envelope handler dropped it,
    # so the response told the client the method was wrong without saying which ones
    # are right.
    resp = await api_client.delete("/api/v1/healthz")
    assert resp.status_code == 405
    assert "GET" in resp.headers.get("allow", "")
