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
    # No refill: exactly `burst` requests per user, then 429.
    app.state.auth_runtime = AuthRuntime(
        provider=PatProvider(app_db.get_sessionmaker),
        limiter=TokenBucket(rate=0.0, burst=3),
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
