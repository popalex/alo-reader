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
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            pool_recycle=settings.db_pool_recycle_s,
            # asyncpg applies these as server parameters on each connection.
            connect_args={
                "server_settings": {"statement_timeout": str(settings.db_statement_timeout_ms)}
            },
        )
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
