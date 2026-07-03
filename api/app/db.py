"""Database engine / session wiring for the API process.

The engine is created lazily from ``DATABASE_URL`` (via settings) on first use.
Route handlers get a session through the :func:`get_session` dependency, which
commits on success and rolls back on any exception. Tests point ``_engine`` /
``_sessionmaker`` at their throwaway Testcontainers database.
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Per-request session: commit on success, roll back on exception."""
    async with get_sessionmaker()() as session:
        async with session.begin():
            yield session
