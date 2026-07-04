"""AUTH_MODE=none — single-user self-host mode (DESIGN.md §0.1).

Auth is disabled: every request maps to one auto-created local user
(``clerk_user_id`` NULL, empty email). Must only run behind a private network /
reverse-proxy auth; the server refuses to default to this mode.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.models import User
from app.store import users as users_store

from .pat import SessionFactory
from .provider import AuthedUser, authed

# pg_advisory_xact_lock key serializing first-user creation ("alo" as an int).
_PROVISION_LOCK_KEY = 0x616C6F


class NoneProvider:
    """Maps every request to the single local user, creating it on first use."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._user_id: int | None = None

    async def authenticate(self, request: Request) -> AuthedUser | None:
        async with self._session_factory()() as session, session.begin():
            if self._user_id is not None:
                user = await users_store.get(session, self._user_id)
                if user is not None:
                    return authed(user)
                self._user_id = None  # user vanished (test DB reset); re-resolve
            user = await self._single_user(session)
            self._user_id = user.id
            return authed(user)

    async def _single_user(self, session: AsyncSession) -> User:
        stmt = select(User).where(User.clerk_user_id.is_(None)).order_by(User.id).limit(1)
        user = (await session.scalars(stmt)).first()
        if user is not None:
            return user
        # Serialize creation across concurrent first requests / replicas.
        await session.execute(select(func.pg_advisory_xact_lock(_PROVISION_LOCK_KEY)))
        user = (await session.scalars(stmt)).first()
        if user is not None:
            return user
        return await users_store.create(session, clerk_user_id=None, email="")
