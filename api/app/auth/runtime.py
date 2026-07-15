"""Auth runtime: provider selection by AUTH_MODE + the `current_user` dependency.

The runtime (provider + per-user rate limiter) is built lazily on first request
and cached on ``app.state.auth_runtime``; tests swap it to pin a mode or inject
a mocked JWKS transport.
"""

from dataclasses import dataclass

import httpx
from fastapi import FastAPI
from starlette.requests import Request

from app import db
from app.config import AUTH_MODES, get_settings
from app.errors import ApiError

from .clerk import ClerkProvider, ClerkSettings
from .none import NoneProvider
from .pat import PatProvider
from .provider import AuthedUser, AuthProvider, ChainProvider
from .ratelimit import TokenBucket


@dataclass
class AuthRuntime:
    provider: AuthProvider
    limiter: TokenBucket  # per-user, post-auth
    ip_limiter: TokenBucket  # per-IP, pre-auth


def build_provider(
    mode: str,
    *,
    clerk_settings: ClerkSettings | None = None,
    clerk_http_client: httpx.AsyncClient | None = None,
) -> AuthProvider:
    """PATs authenticate in every mode; the mode picks the interactive provider."""
    if mode not in AUTH_MODES:
        raise RuntimeError(f"invalid AUTH_MODE {mode!r} (expected one of {AUTH_MODES})")
    providers: list[AuthProvider] = [PatProvider(db.get_sessionmaker)]
    if mode == "clerk":
        providers.append(
            ClerkProvider(
                db.get_sessionmaker, settings=clerk_settings, http_client=clerk_http_client
            )
        )
    else:
        providers.append(NoneProvider(db.get_sessionmaker))
    return ChainProvider(providers)


def get_runtime(app: FastAPI) -> AuthRuntime:
    runtime = getattr(app.state, "auth_runtime", None)
    if runtime is None:
        settings = get_settings()
        if settings.auth_mode is None:
            raise RuntimeError("AUTH_MODE is not set (boot validation should have caught this)")
        runtime = AuthRuntime(
            provider=build_provider(settings.auth_mode),
            limiter=TokenBucket(settings.rate_limit_rps, settings.rate_limit_burst),
            ip_limiter=TokenBucket(settings.rate_limit_ip_rps, settings.rate_limit_ip_burst),
        )
        app.state.auth_runtime = runtime
    return runtime  # type: ignore[no-any-return]


async def current_user(request: Request) -> AuthedUser:
    """FastAPI dependency: the identity attached by the auth middleware, or 401."""
    user = getattr(request.state, "authed_user", None)
    if user is None:
        raise ApiError(401, "unauthenticated", "authentication required")
    return user  # type: ignore[no-any-return]
