"""Per-user token-bucket rate limiting (in-process, per replica)."""

import httpx

from app import db as app_db
from app.auth.pat import PatProvider
from app.auth.ratelimit import TokenBucket
from app.auth.runtime import AuthRuntime
from app.main import app

from .conftest import PatUser, make_pat_user


def test_token_bucket_refills() -> None:
    bucket = TokenBucket(rate=1000.0, burst=2)
    assert bucket.allow(1)
    assert bucket.allow(1)
    # Bucket for user 1 may momentarily be empty, but a high refill rate tops it
    # back up almost immediately; a different user has a full bucket regardless.
    assert bucket.allow(2)


async def test_per_user_rate_limit(api_client: httpx.AsyncClient, pat_user: PatUser) -> None:
    # No refill: exactly `burst` requests per user, then 429. Generous IP limiter so the
    # per-user bucket is what trips.
    app.state.auth_runtime = AuthRuntime(
        provider=PatProvider(app_db.get_sessionmaker),
        limiter=TokenBucket(rate=0.0, burst=3),
        ip_limiter=TokenBucket(rate=1000.0, burst=1000),
    )
    for _ in range(3):
        response = await api_client.get("/api/v1/me", headers=pat_user.headers)
        assert response.status_code == 200

    limited = await api_client.get("/api/v1/me", headers=pat_user.headers)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"

    # The bucket is per user: someone else is unaffected.
    other = await make_pat_user("other@example.com")
    response = await api_client.get("/api/v1/me", headers=other.headers)
    assert response.status_code == 200

    # Public endpoints are not per-user limited.
    config = await api_client.get("/api/v1/config")
    assert config.status_code == 200


async def test_per_ip_pre_auth_limit(api_client: httpx.AsyncClient, api_db: str) -> None:
    # Tight IP bucket, generous per-user: the pre-auth per-IP gate is what trips, and it
    # applies even to unauthenticated requests (which otherwise 401).
    app.state.auth_runtime = AuthRuntime(
        provider=PatProvider(app_db.get_sessionmaker),
        limiter=TokenBucket(rate=1000.0, burst=1000),
        ip_limiter=TokenBucket(rate=0.0, burst=2),
    )
    ip_a = {"X-Real-IP": "1.1.1.1"}
    for _ in range(2):  # pass the IP gate, then fail auth
        assert (await api_client.get("/api/v1/me", headers=ip_a)).status_code == 401
    limited = await api_client.get("/api/v1/me", headers=ip_a)
    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limited"

    # A different client IP has its own bucket (Caddy injects the real one).
    assert (await api_client.get("/api/v1/me", headers={"X-Real-IP": "2.2.2.2"})).status_code == 401

    # Public paths skip the IP gate entirely.
    assert (await api_client.get("/api/v1/config")).status_code == 200
