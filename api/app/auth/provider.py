"""The ``AuthProvider`` seam (DESIGN.md §0.1).

Everything auth-vendor-specific lives behind this small protocol; the rest of
the application only ever sees an :class:`AuthedUser`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from starlette.requests import Request

from app.models import User


@dataclass(frozen=True)
class AuthedUser:
    """The authenticated identity attached to a request."""

    id: int
    email: str
    quota_subs: int


class AuthProvider(Protocol):
    async def authenticate(self, request: Request) -> AuthedUser | None: ...


class ChainProvider:
    """Try providers in order; first non-None identity wins."""

    def __init__(self, providers: Sequence[AuthProvider]) -> None:
        self._providers = providers

    async def authenticate(self, request: Request) -> AuthedUser | None:
        for provider in self._providers:
            user = await provider.authenticate(request)
            if user is not None:
                return user
        return None


def authed(user: User) -> AuthedUser:
    return AuthedUser(id=user.id, email=user.email, quota_subs=user.quota_subs)


def bearer_token(request: Request) -> str | None:
    """Extract a Bearer token from the Authorization header, if any."""
    header = request.headers.get("authorization")
    if header is None:
        return None
    scheme, _, credentials = header.partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        return None
    return credentials.strip()
