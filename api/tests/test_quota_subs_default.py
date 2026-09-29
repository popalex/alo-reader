"""QUOTA_SUBS_DEFAULT: the subscription cap a NEW account gets, stored on its row.

Every path that creates a user row takes it from settings: the single user of
AUTH_MODE=none (here), the Clerk JWT auto-provision (test_auth_clerk.py) and the
user.created webhook (test_webhook_clerk.py). Changing it leaves existing accounts
alone; their cap is per-row, so one can be raised without a migration.
"""

from collections.abc import Callable

import httpx
import pytest
from pydantic import ValidationError

from app import db as app_db
from app.config import Settings
from app.store import users as users_store
from tests.factories import make_user


def test_default_is_300() -> None:
    settings = Settings(database_url="postgresql+asyncpg://x:y@localhost/z")
    assert settings.quota_subs_default == 300


@pytest.mark.parametrize("bad", [0, -1])
def test_rejects_a_non_positive_cap(bad: int) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+asyncpg://x:y@localhost/z", quota_subs_default=bad)


async def test_none_mode_user_gets_the_configured_cap(
    api_client: httpx.AsyncClient,
    set_auth_mode: Callable[[str], None],
    quota_default: Callable[[int], None],
) -> None:
    set_auth_mode("none")
    quota_default(42)
    response = await api_client.get("/api/v1/me")
    assert response.status_code == 200
    assert response.json()["quotas"]["subscriptions"] == 42


async def test_changing_the_default_leaves_existing_accounts_alone(
    api_db: str, quota_default: Callable[[int], None]
) -> None:
    async with app_db.get_sessionmaker()() as s, s.begin():
        existing = await make_user(s)  # created at 300
    quota_default(42)
    async with app_db.get_sessionmaker()() as s:
        again = await users_store.get(s, existing.id)
    assert again is not None and again.quota_subs == 300
