"""Clerk JWT verification against a mocked JWKS endpoint (httpx.MockTransport)."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
import pytest
import pytest_asyncio
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import func, select

from app import db as app_db
from app.auth.clerk import (
    JWKS_MISS_REFRESH_S,
    JWKS_TTL_S,
    ClerkSettings,
    JwksCache,
)
from app.auth.provider import AuthUnavailable
from app.auth.ratelimit import TokenBucket
from app.auth.runtime import AuthRuntime, build_provider
from app.main import app
from app.models import User
from app.store import users as users_store

KID = "test-key-1"
ISSUER = "https://clerk.test.example"
AUDIENCE = "alo-test"


@pytest.fixture(scope="module")
def rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@dataclass
class ClerkEnv:
    key: rsa.RSAPrivateKey
    jwks_fetches: list[int] = field(default_factory=list)

    def make_jwt(self, sub: str = "user_abc", **overrides: Any) -> str:
        kid = overrides.pop("_kid", KID)
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": sub,
            "iat": now,
            "exp": now + 3600,
            "iss": ISSUER,
            "aud": AUDIENCE,
        }
        claims.update(overrides)
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": kid})

    def headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def clerk_env(api_db: str, rsa_key: rsa.RSAPrivateKey) -> AsyncIterator[ClerkEnv]:
    """Install a clerk-mode auth runtime whose JWKS URL is served by MockTransport."""
    env = ClerkEnv(key=rsa_key)
    jwk = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{ISSUER}/.well-known/jwks.json"
        env.jwks_fetches.append(1)
        return httpx.Response(200, json={"keys": [jwk]})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = ClerkSettings(issuer=ISSUER, audience=AUDIENCE, publishable_key="pk_test_visible")
    provider = build_provider("clerk", clerk_settings=settings, clerk_http_client=http_client)
    app.state.auth_runtime = AuthRuntime(
        provider=provider,
        limiter=TokenBucket(1000, 1000),
        ip_limiter=TokenBucket(1000, 1000),
    )
    yield env
    await http_client.aclose()


async def test_valid_jwt_maps_to_local_user(
    api_client: httpx.AsyncClient, clerk_env: ClerkEnv
) -> None:
    async with app_db.get_sessionmaker()() as s, s.begin():
        user = await users_store.create(s, clerk_user_id="user_abc", email="a@example.com")
        user_id = user.id

    response = await api_client.get(
        "/api/v1/me", headers=clerk_env.headers(clerk_env.make_jwt("user_abc"))
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == user_id
    assert body["email"] == "a@example.com"

    async with app_db.get_sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(User)) == 1  # no extra row


async def test_valid_jwt_unknown_user_auto_provisions(
    api_client: httpx.AsyncClient, clerk_env: ClerkEnv
) -> None:
    """Webhook lag: a verified JWT with no local row creates it (pinned decision)."""
    response = await api_client.get(
        "/api/v1/me", headers=clerk_env.headers(clerk_env.make_jwt("user_fresh"))
    )
    assert response.status_code == 200
    async with app_db.get_sessionmaker()() as s:
        user = await users_store.get_by_clerk_id(s, "user_fresh")
    assert user is not None
    assert user.email == ""  # filled later by the user.created/updated webhook
    assert response.json()["id"] == user.id


@pytest.mark.parametrize(
    "overrides",
    [
        {"exp": int(time.time()) - 100},  # expired
        {"aud": "someone-else"},  # wrong audience
        {"iss": "https://evil.example"},  # wrong issuer
        {"sub": ""},  # empty subject
    ],
)
async def test_bad_claims_rejected(
    api_client: httpx.AsyncClient, clerk_env: ClerkEnv, overrides: dict[str, Any]
) -> None:
    token = clerk_env.make_jwt(**{"sub": "user_abc", **overrides})
    response = await api_client.get("/api/v1/me", headers=clerk_env.headers(token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


async def test_garbage_tokens_rejected(api_client: httpx.AsyncClient, clerk_env: ClerkEnv) -> None:
    for token in ("not.a.jwt", "x", "eyJhbGciOiJub25lIn0.e30."):
        response = await api_client.get("/api/v1/me", headers=clerk_env.headers(token))
        assert response.status_code == 401


async def test_wrong_signing_key_rejected(
    api_client: httpx.AsyncClient, clerk_env: ClerkEnv
) -> None:
    imposter = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    token = jwt.encode(
        {"sub": "user_abc", "iat": now, "exp": now + 3600, "iss": ISSUER, "aud": AUDIENCE},
        imposter,
        algorithm="RS256",
        headers={"kid": KID},  # claims the real kid, signed by the wrong key
    )
    response = await api_client.get("/api/v1/me", headers=clerk_env.headers(token))
    assert response.status_code == 401


async def test_unknown_kid_rejected(api_client: httpx.AsyncClient, clerk_env: ClerkEnv) -> None:
    token = clerk_env.make_jwt("user_abc", _kid="no-such-kid")
    response = await api_client.get("/api/v1/me", headers=clerk_env.headers(token))
    assert response.status_code == 401


async def test_jwks_fetched_once_and_cached(
    api_client: httpx.AsyncClient, clerk_env: ClerkEnv
) -> None:
    token = clerk_env.make_jwt("user_cached")
    for _ in range(3):
        response = await api_client.get("/api/v1/me", headers=clerk_env.headers(token))
        assert response.status_code == 200
    assert len(clerk_env.jwks_fetches) == 1  # in-process 1h cache


async def test_config_exposes_publishable_key(
    api_client: httpx.AsyncClient,
    set_auth_mode: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_auth_mode("clerk")
    monkeypatch.setenv("CLERK_PUBLISHABLE_KEY", "pk_test_visible")
    response = await api_client.get("/api/v1/config")
    assert response.status_code == 200
    assert response.json() == {
        "auth_mode": "clerk",
        "clerk_publishable_key": "pk_test_visible",
        "otel_enabled": False,
    }


async def test_one_unbuildable_jwks_key_does_not_break_the_instance(
    api_client: httpx.AsyncClient, api_db: str, rsa_key: rsa.RSAPrivateKey
) -> None:
    # jwt.PyJWK raises on an entry it cannot build, and nothing in the verify path
    # caught it: one bad key in the issuer's document and every request 500s, for
    # every user, permanently, because the cache timestamp is only set on success.
    jwk = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    document = {"keys": [{"kty": "OCT", "kid": "broken"}, jwk]}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=document)

    env = ClerkEnv(key=rsa_key)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.state.auth_runtime = AuthRuntime(
        provider=build_provider(
            "clerk",
            clerk_settings=ClerkSettings(issuer=ISSUER, audience=AUDIENCE),
            clerk_http_client=http_client,
        ),
        limiter=TokenBucket(1000, 1000),
        ip_limiter=TokenBucket(1000, 1000),
    )
    try:
        resp = await api_client.get("/api/v1/me", headers=env.headers(env.make_jwt("user_ok")))
        assert resp.status_code == 200
    finally:
        await http_client.aclose()


async def test_a_key_that_cannot_verify_the_alg_is_a_401(
    api_client: httpx.AsyncClient, api_db: str, rsa_key: rsa.RSAPrivateKey
) -> None:
    # A JWKS entry whose type does not match the token's alg makes jwt.decode raise
    # a bare TypeError from key preparation, which is not an InvalidTokenError: it
    # used to escape as a 500 on an unauthenticated request.
    # Builds fine as an HMAC key, then cannot verify an RS256 token: PyJWT raises a
    # bare TypeError out of key preparation, which is not an InvalidTokenError.
    document = {"keys": [{"kty": "oct", "kid": KID, "alg": "HS256", "k": "c2VjcmV0"}]}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=document)

    env = ClerkEnv(key=rsa_key)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.state.auth_runtime = AuthRuntime(
        provider=build_provider(
            "clerk",
            clerk_settings=ClerkSettings(issuer=ISSUER, audience=AUDIENCE),
            clerk_http_client=http_client,
        ),
        limiter=TokenBucket(1000, 1000),
        ip_limiter=TokenBucket(1000, 1000),
    )
    try:
        resp = await api_client.get("/api/v1/me", headers=env.headers(env.make_jwt("user_y")))
    finally:
        await http_client.aclose()

    assert resp.status_code == 401


async def test_jwks_outage_is_503_not_a_sign_out(
    api_client: httpx.AsyncClient, api_db: str, rsa_key: rsa.RSAPrivateKey
) -> None:
    # 401 tells the SPA the session is invalid and it signs the user out. A JWKS
    # fetch that failed says nothing about the token, so it has to be retryable.
    attempts: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ConnectError("issuer unreachable")

    env = ClerkEnv(key=rsa_key)
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app.state.auth_runtime = AuthRuntime(
        provider=build_provider(
            "clerk",
            clerk_settings=ClerkSettings(issuer=ISSUER, audience=AUDIENCE),
            clerk_http_client=http_client,
        ),
        limiter=TokenBucket(1000, 1000),
        ip_limiter=TokenBucket(1000, 1000),
    )
    try:
        headers = env.headers(env.make_jwt("user_x"))
        first = await api_client.get("/api/v1/me", headers=headers)
        second = await api_client.get("/api/v1/me", headers=headers)
    finally:
        await http_client.aclose()

    assert first.status_code == 503
    assert first.json()["error"]["code"] == "unavailable"
    assert second.status_code == 503
    # The second request rode the failure cooldown instead of opening its own fetch.
    assert len(attempts) == 1


async def test_rotated_kid_is_refetched_within_the_miss_window(
    api_client: httpx.AsyncClient, api_db: str, rsa_key: rsa.RSAPrivateKey
) -> None:
    # Clerk rotates signing keys. The warm-cache refetch exists so a token signed by
    # the new kid does not 401 for the rest of the hour-long TTL; an in-lock check
    # against the TTL rather than the miss window turned it into a no-op.
    old_jwk = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
    old_jwk.update({"kid": "kid-old", "alg": "RS256", "use": "sig"})
    new_jwk = dict(old_jwk, kid=KID)
    documents = [{"keys": [old_jwk]}, {"keys": [old_jwk, new_jwk]}]
    fetches: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        fetches.append(1)
        return httpx.Response(200, json=documents[min(len(fetches) - 1, 1)])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cache = JwksCache(f"{ISSUER}/.well-known/jwks.json", http_client=http_client)
    try:
        assert await cache.get_key("kid-old") is not None  # cold fetch
        cache._fetched_at = time.monotonic() - (JWKS_MISS_REFRESH_S + 1)  # noqa: SLF001
        rotated = await cache.get_key(KID)
    finally:
        await http_client.aclose()

    assert rotated is not None, "the rotated key was never refetched"
    assert len(fetches) == 2


async def test_an_outage_serves_the_keys_already_held(
    api_client: httpx.AsyncClient, api_db: str, rsa_key: rsa.RSAPrivateKey
) -> None:
    # Keys in memory still verify the tokens they signed. Once the TTL lapsed, a
    # refresh failure used to 503 the whole instance for the length of the outage.
    jwk = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    fetches: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        fetches.append(1)
        if len(fetches) == 1:
            return httpx.Response(200, json={"keys": [jwk]})
        raise httpx.ConnectError("issuer unreachable")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cache = JwksCache(f"{ISSUER}/.well-known/jwks.json", http_client=http_client)
    try:
        assert await cache.get_key(KID) is not None
        cache._fetched_at = time.monotonic() - (JWKS_TTL_S + 1)  # noqa: SLF001
        during_outage = await cache.get_key(KID)
    finally:
        await http_client.aclose()

    assert during_outage is not None, "held keys were discarded during an outage"


async def test_an_empty_key_document_does_not_replace_a_good_cache(
    api_client: httpx.AsyncClient, api_db: str, rsa_key: rsa.RSAPrivateKey
) -> None:
    jwk = json.loads(RSAAlgorithm.to_jwk(rsa_key.public_key()))
    jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    documents: list[dict[str, object]] = [{"keys": [jwk]}, {"keys": []}]
    fetches: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        fetches.append(1)
        return httpx.Response(200, json=documents[min(len(fetches) - 1, 1)])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    cache = JwksCache(f"{ISSUER}/.well-known/jwks.json", http_client=http_client)
    try:
        assert await cache.get_key(KID) is not None
        cache._fetched_at = time.monotonic() - (JWKS_TTL_S + 1)  # noqa: SLF001
        after_empty = await cache.get_key(KID)
    finally:
        await http_client.aclose()

    assert after_empty is not None, "an empty document wiped the working keys"


async def test_a_failing_fetch_is_attempted_once_for_all_waiters(
    api_client: httpx.AsyncClient, api_db: str
) -> None:
    # Every request that arrives during a failing fetch queues on the lock. Checking
    # the cooldown only before the lock meant each waiter then ran its own fetch in
    # turn, so an outage serialized into minutes of waiting.
    fetches: list[int] = []

    async def slow_failure(_request: httpx.Request) -> httpx.Response:
        fetches.append(1)
        await asyncio.sleep(0.05)
        raise httpx.ConnectError("issuer unreachable")

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(slow_failure))
    cache = JwksCache(f"{ISSUER}/.well-known/jwks.json", http_client=http_client)
    try:
        results = await asyncio.gather(
            *(cache.get_key(KID) for _ in range(10)), return_exceptions=True
        )
    finally:
        await http_client.aclose()

    assert all(isinstance(r, AuthUnavailable) for r in results)
    assert len(fetches) == 1, f"one fetch expected for ten waiters, got {len(fetches)}"
