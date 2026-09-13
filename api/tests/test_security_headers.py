"""Security-header audit (WP-15, DESIGN.md §1.6).

Asserts an API response carries *exactly* the audited header set — value for value —
and that they're present on unauthenticated errors and on a 500 too. The 500 is the
case that shipped broken: Starlette hands an Exception handler to ServerErrorMiddleware,
which wraps every user middleware, so that response never passed through the header
middleware and went out with none of these at all.
If the set in app.security changes, this test changes with it, on purpose.
"""

from collections.abc import Callable

import httpx

from app.security import SECURITY_HEADERS

# Header names are case-insensitive; assert against a normalized view.
_EXPECTED = {k.lower(): v for k, v in SECURITY_HEADERS.items()}


def _present_security_headers(resp: httpx.Response) -> dict[str, str]:
    return {k.lower(): v for k, v in resp.headers.items() if k.lower() in _EXPECTED}


async def test_exact_header_set_on_ok(api_client: httpx.AsyncClient) -> None:
    resp = await api_client.get("/api/v1/healthz")
    assert resp.status_code == 200
    # Every expected header present with its exact value, and none missing.
    assert _present_security_headers(resp) == _EXPECTED


async def test_csp_locks_api_to_nothing() -> None:
    # The API CSP must be the tightest — it sources no resources.
    assert SECURITY_HEADERS["Content-Security-Policy"].startswith("default-src 'none'")
    assert SECURITY_HEADERS["X-Frame-Options"] == "DENY"


async def test_headers_present_on_unauthenticated_error(
    api_client: httpx.AsyncClient,
    set_auth_mode: Callable[[str], None],
) -> None:
    # A protected route with no credentials → 401, but the headers still land
    # (SecurityHeadersMiddleware wraps the auth middleware).
    set_auth_mode("clerk")
    resp = await api_client.get("/api/v1/subscriptions")
    assert resp.status_code == 401
    assert _present_security_headers(resp) == _EXPECTED


async def test_exact_header_set_on_unhandled_error() -> None:
    """A 500 must carry the same audited set as a 200.

    It is built by ServerErrorMiddleware, outside the middleware that normally adds
    these, so errors.py applies them itself. Without that, the one response most likely
    to be rendered in a browser during an incident had no nosniff and no frame-ancestors.
    """
    import httpx as _httpx
    from fastapi import FastAPI

    from app.errors import register_exception_handlers

    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom")

    transport = _httpx.ASGITransport(app=test_app, raise_app_exceptions=False)
    async with _httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/boom")

    assert resp.status_code == 500
    assert _present_security_headers(resp) == _EXPECTED
