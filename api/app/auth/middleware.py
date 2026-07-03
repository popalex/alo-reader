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

# Paths that never need an identity: skipped entirely (healthz must not touch
# the DB, /config is the SPA's pre-auth boot call, the webhook is svix-signed).
PUBLIC_PATHS = frozenset({"/api/v1/healthz", "/api/v1/config", "/api/v1/webhooks/clerk"})


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        runtime = get_runtime(request.app)
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
