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

import asyncio
import time

import httpx
import jwt
from jwt.types import Options as JwtOptions
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.store import users as users_store

from .pat import TOKEN_PREFIX, SessionFactory
from .provider import AuthedUser, AuthUnavailable, authed, bearer_token

JWKS_TTL_S = 3600
# Refetch at most this often when an unknown kid shows up (key rotation).
JWKS_MISS_REFRESH_S = 60
# After a failed fetch, answer 503 for this long instead of hammering a down issuer.
JWKS_FAILURE_COOLDOWN_S = 10


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
        self._failed_at: float | None = None
        # One refresh at a time. Without it, an upstream that is slow or down has
        # every concurrent request open its own 10s fetch, and the pile-up outlives
        # the outage.
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        client = self._client
        if client is None:
            async with httpx.AsyncClient(timeout=10) as owned:
                response = await owned.get(self._url)
        else:
            response = await client.get(self._url)
        response.raise_for_status()
        try:
            document = response.json()
        except ValueError as exc:  # a proxy's error page, say
            raise AuthUnavailable("JWKS response was not JSON") from exc
        keys: dict[str, jwt.PyJWK] = {}
        for entry in document.get("keys", []) if isinstance(document, dict) else []:
            # Skip what we cannot build instead of raising, exactly as PyJWT's own
            # PyJWKSet does. One unusable entry in the issuer's document would
            # otherwise fail every request, for every user, including the ones whose
            # key parsed fine — and since _fetched_at stays unset on the failure path,
            # every following request retries and fails the same way.
            try:
                key = jwt.PyJWK(entry)
            except Exception:  # noqa: BLE001 — any malformed entry, whatever the shape
                continue
            if key.key_id is not None:
                keys[key.key_id] = key
        if not keys:
            # An empty document, a JSON array, or every entry skipped above. Caching
            # that as a success would discard working keys and 401 everyone until the
            # TTL lapses; the caller keeps what it has and answers 503 instead.
            raise AuthUnavailable("JWKS contained no usable keys")
        self._keys = keys
        self._fetched_at = time.monotonic()

    async def get_key(self, kid: str | None) -> jwt.PyJWK | None:
        if kid is None:
            return None
        now = time.monotonic()
        stale = self._fetched_at is None or now - self._fetched_at >= JWKS_TTL_S
        if stale:
            await self._refresh_once(JWKS_TTL_S)
        key = self._keys.get(kid)
        if key is None and not stale and self._fetched_at is not None:
            # Unknown kid on a warm cache: allow one refetch per minute so key
            # rotation doesn't lock users out for the full TTL. The age to beat is
            # the miss window, not the TTL — passing the TTL here would make every
            # one of these calls a no-op, since this branch only runs on a cache
            # younger than the TTL, and rotation would lock users out for an hour.
            if now - self._fetched_at >= JWKS_MISS_REFRESH_S:
                await self._refresh_once(JWKS_MISS_REFRESH_S)
                key = self._keys.get(kid)
        return key

    async def _refresh_once(self, min_age_s: float) -> None:
        """Refresh under a lock, skipping the fetch if the cache is younger than
        ``min_age_s`` (someone else just did it) and backing off after a failure.

        Raises :class:`AuthUnavailable` only when there is nothing usable to fall
        back on, so the caller answers 503 instead of pretending the token was bad.
        """
        async with self._lock:
            now = time.monotonic()
            # Both checks belong inside the lock. Outside it, every request that
            # arrived during a failing 10s fetch passes the cooldown gate, queues on
            # the lock, and then runs its own fetch in turn: an outage serializes into
            # minutes of waiting, which is what the lock is here to prevent.
            if self._fetched_at is not None and now - self._fetched_at < min_age_s:
                return
            if self._failed_at is not None and now - self._failed_at < JWKS_FAILURE_COOLDOWN_S:
                if self._keys:
                    return
                raise AuthUnavailable("JWKS is unreachable")
            try:
                await self._refresh()
            except (httpx.HTTPError, AuthUnavailable) as exc:
                self._failed_at = time.monotonic()
                if self._keys:
                    # Keys we already hold still verify the tokens they signed. An
                    # expired TTL is not a reason to 503 a whole instance through an
                    # issuer outage; it is a reason to try again on the next request.
                    return
                raise AuthUnavailable(str(exc) or "JWKS fetch failed") from exc
            self._failed_at = None


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
        # get_key raises AuthUnavailable when the issuer cannot be reached, which
        # the middleware answers with 503. An outage says nothing about this token.
        key = await self._jwks.get_key(header.get("kid"))
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
        except jwt.PyJWTError, TypeError, ValueError:
            # PyJWTError covers the invalid-token family and the key-handling errors
            # beside it (PyJWKError, InvalidKeyError), which are siblings rather than
            # subclasses of InvalidTokenError. TypeError/ValueError catch the key
            # preparation failures underneath: a JWKS entry whose type does not match
            # the token's alg makes jwt.decode raise a bare "Expecting a PEM-formatted
            # key", which used to escape as a 500 on an unauthenticated request.
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
        except IntegrityError as exc:
            # Lost the auto-provision race: the winner's row is there to re-read.
            # If it is not, the constraint that fired was a different one, and an
            # assert would both lie about that and vanish under python -O.
            async with self._session_factory()() as session, session.begin():
                user = await users_store.get_by_clerk_id(session, clerk_user_id)
                if user is None:
                    raise AuthUnavailable("could not provision the local user") from exc
                return authed(user)
