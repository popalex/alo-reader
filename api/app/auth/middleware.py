"""ASGI middleware: authenticate the request, then rate-limit per user.

Authentication happens once here; the result is stashed in ``request.state``
for the `current_user` dependency. Unauthenticated requests pass through (the
dependency 401s on protected routes) and are not rate-limited per user.
"""

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.errors import error_envelope

from .provider import AuthUnavailable
from .runtime import get_runtime

# Paths that never need an identity: skipped entirely (healthz must not touch the DB,
# /config is the SPA's pre-auth boot call, and the webhook is svix-signed).
PUBLIC_PATHS = frozenset({"/api/v1/healthz", "/api/v1/config", "/api/v1/webhooks/clerk"})
# Served favicons are global, immutable bytes referenced from <img> tags — public.
PUBLIC_PREFIXES = ("/api/v1/icons/",)


# The liveness probe: no identity, no database, and never rate-limited. A 429'd
# health check restarts a container that was fine.
PROBE_PATHS = frozenset({"/api/v1/healthz"})


def _normalize(path: str) -> str:
    """Trailing slashes are the same route to Starlette (it 307s), so they must be
    the same route here too. Otherwise /api/v1/healthz/ runs the whole provider
    chain, including the DB lookup that healthz exists to avoid, before redirecting."""
    return path.rstrip("/") or "/"


def _is_public(path: str) -> bool:
    normalized = _normalize(path)
    return normalized in PUBLIC_PATHS or normalized.startswith(PUBLIC_PREFIXES)


def _is_probe(path: str) -> bool:
    return _normalize(path) in PROBE_PATHS


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
        if scope["type"] != "http" or _is_probe(scope["path"]):
            await self.app(scope, receive, send)
            return
        request = Request(scope, receive)
        runtime = get_runtime(request.app)
        # Per-IP gate BEFORE the provider chain: bounds the pre-auth cost (a DB lookup
        # for an invalid PAT, a signature verify for a bogus JWT) that an unauthenticated
        # client could otherwise force per request.
        #
        # Public paths are gated too, and they are the ones that need it most: the
        # webhook reads an unbounded body and runs an HMAC verify plus DB writes, and
        # an icon read streams a blob, both unauthenticated. Caddy sets no rate limit,
        # so this middleware is the only gate in front of them. They get their own,
        # looser bucket: one page load fetches an icon per subscription, and sharing
        # the API bucket would let a cold first load 429 its own images.
        public = _is_public(scope["path"])
        limiter = runtime.public_limiter if public else runtime.ip_limiter
        if not limiter.allow(client_ip(request)):
            response = JSONResponse(
                status_code=429,
                content=error_envelope("rate_limited", "too many requests"),
            )
            await response(scope, receive, send)
            return
        if public:
            await self.app(scope, receive, send)
            return
        try:
            user = await runtime.provider.authenticate(request)
        except AuthUnavailable:
            # An upstream is down (the issuer's JWKS, or the DB behind
            # auto-provisioning). 401 would sign every signed-in user out of the SPA
            # over something transient; 503 is retryable and honest.
            response = JSONResponse(
                status_code=503,
                content=error_envelope("unavailable", "authentication is unavailable"),
            )
            await response(scope, receive, send)
            return
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
