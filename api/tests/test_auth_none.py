"""AUTH_MODE=none: every request maps to one auto-created local user."""

from collections.abc import Callable

import httpx
from sqlalchemy import select

from app import db as app_db
from app.models import User


async def test_none_mode_auto_user(
    api_client: httpx.AsyncClient, set_auth_mode: Callable[[str], None]
) -> None:
    set_auth_mode("none")

    first = await api_client.get("/api/v1/me")  # no Authorization header at all
    assert first.status_code == 200
    user_id = first.json()["id"]

    second = await api_client.get("/api/v1/me")
    assert second.status_code == 200
    assert second.json()["id"] == user_id  # stable identity across requests

    async with app_db.get_sessionmaker()() as s:
        users = list(await s.scalars(select(User)))
    assert len(users) == 1  # exactly one auto-created user
    assert users[0].id == user_id
    assert users[0].clerk_user_id is None
    assert users[0].email == ""


async def test_none_mode_config_endpoint(
    api_client: httpx.AsyncClient, set_auth_mode: Callable[[str], None]
) -> None:
    set_auth_mode("none")
    response = await api_client.get("/api/v1/config")
    assert response.status_code == 200
    assert response.json() == {"auth_mode": "none"}  # no publishable key leaked


async def test_none_mode_tokens_work(
    api_client: httpx.AsyncClient, set_auth_mode: Callable[[str], None]
) -> None:
    """PATs can be minted and used in none mode (curl/scripts path)."""
    set_auth_mode("none")
    created = await api_client.post("/api/v1/tokens", json={"label": "curl"})
    assert created.status_code == 201
    token = created.json()["token"]

    me_anon = await api_client.get("/api/v1/me")
    me_pat = await api_client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me_pat.status_code == 200
    assert me_pat.json()["id"] == me_anon.json()["id"]
