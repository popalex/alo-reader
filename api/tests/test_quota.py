"""Quota audit (WP-15, DESIGN.md §1.4): the limits added by the hardening pass.

The pre-existing quotas already have bypass tests elsewhere — subscription count
(test_subscriptions_api::test_quota_exceeded_is_422), OPML size + import quota
(test_opml_api), manual refresh spacing (test_subscriptions_api::
test_refresh_rate_limited), and the per-user request bucket (test_ratelimit). This
file covers the two gaps this WP closes: the API-token count cap and the per-user
discovery cooldown. Each asserts a bypass attempt fails.
"""

from collections.abc import Callable, Iterator

import httpx
import pytest

from app.config import get_settings
from app.routes import discover as discover_mod
from app.worker.http import GetResult

from .conftest import PatUser

TOKENS = "/api/v1/tokens"
DISCOVER = "/api/v1/discover"


@pytest.fixture
def set_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str, str], None]]:
    """Override a config env var for one test (settings are lru_cached)."""

    def _set(key: str, value: str) -> None:
        monkeypatch.setenv(key, value)
        get_settings.cache_clear()

    yield _set
    get_settings.cache_clear()


async def test_api_token_count_cap(
    api_client: httpx.AsyncClient, pat_user: PatUser, set_config: Callable[[str, str], None]
) -> None:
    # Cap at 3; the fixture user already holds one ("test"), so two more succeed.
    set_config("QUOTA_API_TOKENS", "3")
    for i in range(2):
        resp = await api_client.post(TOKENS, json={"label": f"t{i}"}, headers=pat_user.headers)
        assert resp.status_code == 201

    # The fourth (count == cap) is refused — the bypass fails.
    over = await api_client.post(TOKENS, json={"label": "over"}, headers=pat_user.headers)
    assert over.status_code == 422
    assert over.json()["error"]["code"] == "quota_exceeded"

    # Deleting one frees a slot again (the cap is on live count, not lifetime).
    listing = (await api_client.get(TOKENS, headers=pat_user.headers)).json()
    await api_client.delete(f"{TOKENS}/{listing[0]['id']}", headers=pat_user.headers)
    again = await api_client.post(TOKENS, json={"label": "after-delete"}, headers=pat_user.headers)
    assert again.status_code == 201


def _stub_discover(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake(url: str, **kwargs: object) -> GetResult:
        return GetResult(ok=False, status=502, final_url=url)

    monkeypatch.setattr(discover_mod, "guarded_get", fake)


async def test_discover_is_rate_limited_per_user(
    api_client: httpx.AsyncClient, pat_user: PatUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_discover(monkeypatch)
    first = await api_client.post(
        DISCOVER, json={"url": "https://blog.example/"}, headers=pat_user.headers
    )
    assert first.status_code == 200

    # A second call inside the cooldown window is refused — hammering the fetcher fails.
    second = await api_client.post(
        DISCOVER, json={"url": "https://other.example/"}, headers=pat_user.headers
    )
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "rate_limited"


async def test_discover_cooldown_is_per_user(
    api_client: httpx.AsyncClient,
    pat_user: PatUser,
    monkeypatch: pytest.MonkeyPatch,
    set_auth_mode: Callable[[str], None],
) -> None:
    from .conftest import make_pat_user

    _stub_discover(monkeypatch)
    first = await api_client.post(
        DISCOVER, json={"url": "https://blog.example/"}, headers=pat_user.headers
    )
    assert first.status_code == 200
    assert (
        await api_client.post(
            DISCOVER, json={"url": "https://blog.example/"}, headers=pat_user.headers
        )
    ).status_code == 429

    # A different user has an independent cooldown.
    other = await make_pat_user("other-discover@example.com")
    resp = await api_client.post(
        DISCOVER, json={"url": "https://blog.example/"}, headers=other.headers
    )
    assert resp.status_code == 200
