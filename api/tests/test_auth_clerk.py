"""Clerk JWT verification against a mocked JWKS endpoint (httpx.MockTransport)."""

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
from app.auth.clerk import ClerkSettings
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
