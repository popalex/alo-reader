"""Test fixtures.

DB tests run against an **ephemeral Testcontainers Postgres** (never a real/dev DB):
a session-scoped container is started, the Alembic migration is applied once, and
each test runs inside an outer transaction that is rolled back on teardown, so tests
never see each other's writes.

API tests (which exercise the app end-to-end, including commits) get a **fresh
database per test** via the ``api_db`` fixture: the migrated session database is
used as a CREATE DATABASE template, so every API test starts from a pristine
empty schema and full isolation.
"""

import itertools
import os
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer  # type: ignore[import-untyped]

# Ambient auth mode for the suite; `AUTH_MODE=clerk pytest api` overrides it.
# Tests that depend on a specific mode pin it via the `set_auth_mode` fixture.
os.environ.setdefault("AUTH_MODE", "none")

from app import db as app_db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402

API_DIR = Path(__file__).resolve().parents[1]

_db_seq = itertools.count(1)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """Start a throwaway Postgres and apply the migration once for the session.

    Uses the project's Postgres image (postgres:18 + the rum extension migration
    0003 needs); override with ALO_TEST_PG_IMAGE. Build it with `make pg-image`."""
    image = os.getenv("ALO_TEST_PG_IMAGE", "alo-reader-postgres:local")
    with PostgresContainer(image, driver="asyncpg") as pg:
        url = pg.get_connection_url()
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        cfg = Config(str(API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(API_DIR / "migrations"))
        command.upgrade(cfg, "head")
        yield url


@pytest_asyncio.fixture
async def engine(database_url: str) -> AsyncIterator[object]:
    eng = create_async_engine(database_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def session(engine: object) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:  # type: ignore[attr-defined]
        trans = await conn.begin()
        db = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield db
        finally:
            await db.close()
            await trans.rollback()


def _clear_auth_runtime() -> None:
    if hasattr(app.state, "auth_runtime"):
        del app.state.auth_runtime


@pytest_asyncio.fixture
async def api_db(database_url: str) -> AsyncIterator[str]:
    """Fresh migrated database for one API test, wired into the app's engine."""
    template = make_url(database_url)
    name = f"api_test_{next(_db_seq)}"
    admin = await asyncpg.connect(
        host=template.host,
        port=template.port,
        user=template.username,
        password=template.password,
        database="postgres",
    )
    try:
        await admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template.database}"')
    finally:
        await admin.close()

    url = template.set(database=name)
    engine = create_async_engine(url, poolclass=NullPool)
    old_engine, old_sessionmaker = app_db._engine, app_db._sessionmaker
    app_db._engine = engine
    app_db._sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    _clear_auth_runtime()
    try:
        yield url.render_as_string(hide_password=False)
    finally:
        await engine.dispose()
        app_db._engine, app_db._sessionmaker = old_engine, old_sessionmaker
        _clear_auth_runtime()


@pytest_asyncio.fixture
async def api_client(api_db: str) -> AsyncIterator[httpx.AsyncClient]:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def set_auth_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str], None]]:
    """Pin AUTH_MODE for one test regardless of the ambient suite mode."""

    def _set(mode: str) -> None:
        monkeypatch.setenv("AUTH_MODE", mode)
        get_settings.cache_clear()
        _clear_auth_runtime()

    yield _set
    get_settings.cache_clear()
    _clear_auth_runtime()


@dataclass
class PatUser:
    user_id: int
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


async def make_pat_user(email: str = "pat@example.com") -> PatUser:
    """Create a committed user + PAT in the current api_db."""
    from app.auth import pat
    from app.store import users as users_store

    async with app_db.get_sessionmaker()() as s, s.begin():
        user = await users_store.create(s, email=email)
        _, token = await pat.create(s, user.id, label="test")
        return PatUser(user_id=user.id, token=token)


@pytest_asyncio.fixture
async def pat_user(api_db: str) -> PatUser:
    return await make_pat_user()


@pytest.fixture(autouse=True)
def _reset_cooldowns() -> Iterator[None]:
    """The per-feed refresh and per-user discover cooldowns are process-global; feed
    and user ids repeat across the fresh per-test databases, so clear them between
    tests to avoid cross-test bleed."""
    from app.routes import discover, subscriptions

    subscriptions._refresh_cooldown.reset()
    discover._discover_cooldown.reset()
    yield


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the SSRF resolver treat every host as a public IP (worker/fetch tests)."""
    from app.worker import ssrf

    async def fake(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(ssrf, "resolve", fake)
