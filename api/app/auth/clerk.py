"""AUTH_MODE=clerk — Clerk session-JWT verification (DESIGN.md §0.1, §1.2).

The API verifies ``Authorization: Bearer <session JWT>`` against Clerk's JWKS
(fetched once and cached in-process for 1h) checking issuer, audience, and
expiry, then maps the token's ``sub`` (the Clerk user id) to the local ``users``
row. A valid JWT whose local row is missing (webhook lag/loss) auto-provisions
the row with an empty email — the ``user.created``/``user.updated`` webhook
fills it in later (pinned in MILESTONES.md WP-02).

This module is the ONLY place (plus the routes/webhook wiring in this package)
allowed to know about Clerk.
"""

import time

import httpx
import jwt
from jwt.types import Options as JwtOptions
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.store import users as users_store

from .pat import TOKEN_PREFIX, SessionFactory
from .provider import AuthedUser, authed, bearer_token

JWKS_TTL_S = 3600
# Refetch at most this often when an unknown kid shows up (key rotation).
JWKS_MISS_REFRESH_S = 60


class ClerkSettings(BaseSettings):
    """Clerk-specific configuration, read from CLERK_* environment variables."""

    model_config = SettingsConfigDict(env_prefix="clerk_", extra="ignore")

    # e.g. https://your-app.clerk.accounts.dev — also the JWT `iss` claim.
    issuer: str = ""
    # Expected `aud` claim. Clerk session tokens carry `aud` only when the JWT
    # template sets one; leave empty to skip the audience check.
    audience: str = ""
    publishable_key: str = ""
    # svix signing secret for POST /webhooks/clerk (whsec_...).
    webhook_secret: str = ""

    @property
    def jwks_url(self) -> str:
        return self.issuer.rstrip("/") + "/.well-known/jwks.json"


class JwksCache:
    """In-process JWKS cache: one fetch, reused for JWKS_TTL_S."""

    def __init__(self, url: str, http_client: httpx.AsyncClient | None = None) -> None:
        self._url = url
        self._client = http_client
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None

    async def _refresh(self) -> None:
        client = self._client
        if client is None:
            async with httpx.AsyncClient(timeout=10) as owned:
                response = await owned.get(self._url)
        else:
            response = await client.get(self._url)
        response.raise_for_status()
        keys: dict[str, jwt.PyJWK] = {}
        for entry in response.json().get("keys", []):
            key = jwt.PyJWK(entry)
            if key.key_id is not None:
                keys[key.key_id] = key
        self._keys = keys
        self._fetched_at = time.monotonic()

    async def get_key(self, kid: str | None) -> jwt.PyJWK | None:
        if kid is None:
            return None
        now = time.monotonic()
        stale = self._fetched_at is None or now - self._fetched_at >= JWKS_TTL_S
        if stale:
            await self._refresh()
        key = self._keys.get(kid)
        if key is None and not stale and self._fetched_at is not None:
            # Unknown kid on a warm cache: allow one refetch per minute so key
            # rotation doesn't lock users out for the full TTL.
            if now - self._fetched_at >= JWKS_MISS_REFRESH_S:
                await self._refresh()
                key = self._keys.get(kid)
        return key


class ClerkProvider:
    """Verifies Clerk session JWTs and maps them to local users."""

    def __init__(
        self,
        session_factory: SessionFactory,
        settings: ClerkSettings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings or ClerkSettings()
        self._jwks = JwksCache(self._settings.jwks_url, http_client=http_client)

    async def authenticate(self, request: Request) -> AuthedUser | None:
        token = bearer_token(request)
        if token is None or token.startswith(TOKEN_PREFIX):
            return None
        claims = await self._verify(token)
        if claims is None:
            return None
        clerk_user_id = claims.get("sub")
        if not isinstance(clerk_user_id, str) or not clerk_user_id:
            return None
        return await self._local_user(clerk_user_id)

    async def _verify(self, token: str) -> dict[str, object] | None:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            return None
        try:
            key = await self._jwks.get_key(header.get("kid"))
        except httpx.HTTPError:
            return None
        if key is None:
            return None
        audience = self._settings.audience or None
        options: JwtOptions = {"require": ["exp", "sub"]}
        if audience is None:
            options["verify_aud"] = False
        try:
            claims = jwt.decode(
                token,
                key=key.key,
                algorithms=["RS256"],
                audience=audience,
                issuer=self._settings.issuer,
                options=options,
            )
        except jwt.InvalidTokenError:
            return None
        return dict(claims)

    async def _local_user(self, clerk_user_id: str) -> AuthedUser:
        async with self._session_factory()() as session, session.begin():
            user = await users_store.get_by_clerk_id(session, clerk_user_id)
            if user is not None:
                return authed(user)
        # Webhook hasn't created the row yet: auto-provision (empty email; the
        # user.created/updated webhook fills it). Racing requests can collide on
        # the unique clerk_user_id — loser re-reads.
        try:
            async with self._session_factory()() as session, session.begin():
                user = await users_store.create(session, clerk_user_id=clerk_user_id)
                return authed(user)
        except IntegrityError:
            async with self._session_factory()() as session, session.begin():
                user = await users_store.get_by_clerk_id(session, clerk_user_id)
                assert user is not None
                return authed(user)
