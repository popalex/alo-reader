"""Per-user token-bucket rate limiting (in-process, per replica)."""

import httpx
import pytest
from pydantic import ValidationError

from app import db as app_db
from app.auth.middleware import _is_probe, _is_public
from app.auth.pat import PatProvider
from app.auth.ratelimit import TokenBucket
from app.auth.runtime import AuthRuntime
from app.config import Settings
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


async def test_public_paths_are_rate_limited_but_the_probe_is_not(
    api_client: httpx.AsyncClient,
) -> None:
    # The webhook reads an unbounded body and runs an HMAC verify plus DB writes, and
    # an icon read streams a blob: both unauthenticated, and Caddy sets no rate limit,
    # so this middleware is the only gate in front of them. healthz stays exempt, or a
    # 429'd liveness probe restarts a container that was fine.
    app.state.auth_runtime = AuthRuntime(
        provider=PatProvider(app_db.get_sessionmaker),
        limiter=TokenBucket(rate=1000.0, burst=1000),
        ip_limiter=TokenBucket(rate=0.0, burst=2),  # no refill: exactly 2 then 429
    )
    try:
        statuses = [
            (await api_client.get("/api/v1/config")).status_code,
            (await api_client.get("/api/v1/config")).status_code,
            (await api_client.get("/api/v1/config")).status_code,
        ]
        probes = [(await api_client.get("/api/v1/healthz")).status_code for _ in range(5)]
    finally:
        del app.state.auth_runtime

    assert statuses[-1] == 429
    assert probes == [200] * 5


async def test_healthz_with_a_trailing_slash_is_still_the_probe() -> None:
    # Starlette 307s the trailing-slash form to the same route, so treating it as a
    # different path ran the whole provider chain (a DB round-trip) first, against the
    # route's own promise to stay DB-free.
    assert _is_probe("/api/v1/healthz/") is True
    assert _is_public("/api/v1/icons/12/") is True
    assert _is_probe("/api/v1/entries") is False


def test_zero_refill_rate_is_rejected() -> None:
    # A bucket that never refills cannot survive idle pruning: the sweep drops a
    # drained bucket after the prune interval and the next request recreates it full,
    # silently resetting the limit. The pruning comment claims to be
    # behavior-preserving, and with a positive rate it is.
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+asyncpg://x/y", auth_mode="none", rate_limit_rps=0)
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+asyncpg://x/y", auth_mode="none", rate_limit_ip_rps=0)
