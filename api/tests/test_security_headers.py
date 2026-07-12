"""Security-header audit (WP-15, DESIGN.md §1.6).

Asserts an API response carries *exactly* the audited header set — value for value —
and that they're present on unauthenticated errors too (the middleware is outermost).
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
