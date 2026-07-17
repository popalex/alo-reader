"""ASGI middleware: authenticate the request, then rate-limit per user.

Authentication happens once here; the result is stashed in ``request.state``
for the `current_user` dependency. Unauthenticated requests pass through (the
dependency 401s on protected routes) and are not rate-limited per user.
"""

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.errors import error_envelope

from .runtime import get_runtime

# Paths that never need an identity: skipped entirely (healthz must not touch the DB,
# /config is the SPA's pre-auth boot call, and the webhook is svix-signed).
PUBLIC_PATHS = frozenset({"/api/v1/healthz", "/api/v1/config", "/api/v1/webhooks/clerk"})
# Served favicons are global, immutable bytes referenced from <img> tags — public.
PUBLIC_PREFIXES = ("/api/v1/icons/",)


def _is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def client_ip(request: Request) -> str:
    """The real client IP for per-IP rate limiting.

    Caddy (the edge) injects it as ``X-Real-IP`` (overwrite semantics), and the app is
    only reachable through Caddy — 8000 is unpublished — so the header can't be spoofed.
    Fall back to the socket peer when the header is absent (local dev / tests)."""
    header = request.headers.get("x-real-ip")
    if header:
        return header.strip()
    client = request.client
    return client.host if client is not None else "unknown"


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or _is_public(scope["path"]):
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        runtime = get_runtime(request.app)
        # Per-IP gate BEFORE the provider chain: bounds the pre-auth cost (a DB lookup
        # for an invalid PAT, a signature verify for a bogus JWT) that an unauthenticated
        # client could otherwise force per request.
        if not runtime.ip_limiter.allow(client_ip(request)):
            response = JSONResponse(
                status_code=429,
                content=error_envelope("rate_limited", "too many requests"),
            )
            await response(scope, receive, send)
            return
        user = await runtime.provider.authenticate(request)
        if user is not None:
            if not runtime.limiter.allow(user.id):
                response = JSONResponse(
                    status_code=429,
                    content=error_envelope("rate_limited", "too many requests"),
                )
                await response(scope, receive, send)
                return
            scope.setdefault("state", {})["authed_user"] = user
        await self.app(scope, receive, send)
