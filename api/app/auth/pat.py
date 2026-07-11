"""Personal access tokens (PATs) for programmatic API access.

Tokens look like ``alo_pat_<random>``; only the sha256 of the full token is
stored (``api_tokens.token_hash``), compared constant-time. PATs authenticate in
every AUTH_MODE — they are how curl/scripts talk to the API.
"""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from app.models import ApiToken, User
from app.store import rowcount

from .provider import AuthedUser, authed, bearer_token

TOKEN_PREFIX = "alo_pat_"

SessionFactory = Callable[[], async_sessionmaker[AsyncSession]]


def generate_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


async def create(session: AsyncSession, user_id: int, *, label: str) -> tuple[ApiToken, str]:
    """Create a PAT; returns the row and the plaintext token (shown exactly once)."""
    token = generate_token()
    row = ApiToken(user_id=user_id, token_hash=hash_token(token), label=label)
    session.add(row)
    await session.flush()
    return row, token


async def count_for_user(session: AsyncSession, user_id: int) -> int:
    """Number of PATs a user holds (for the per-user token-count quota)."""
    result = await session.scalar(
        select(func.count()).select_from(ApiToken).where(ApiToken.user_id == user_id)
    )
    return result or 0


async def list_for_user(session: AsyncSession, user_id: int) -> list[ApiToken]:
    result = await session.scalars(
        select(ApiToken).where(ApiToken.user_id == user_id).order_by(ApiToken.id)
    )
    return list(result)


async def delete(session: AsyncSession, user_id: int, token_id: int) -> bool:
    from sqlalchemy import delete as sql_delete

    result = await session.execute(
        sql_delete(ApiToken).where(ApiToken.id == token_id, ApiToken.user_id == user_id)
    )
    return rowcount(result) > 0


class PatProvider:
    """Authenticates ``Authorization: Bearer alo_pat_...`` requests."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    async def authenticate(self, request: Request) -> AuthedUser | None:
        token = bearer_token(request)
        if token is None or not token.startswith(TOKEN_PREFIX):
            return None
        digest = hash_token(token)
        async with self._session_factory()() as session, session.begin():
            result = await session.execute(
                select(ApiToken, User)
                .join(User, User.id == ApiToken.user_id)
                .where(ApiToken.token_hash == digest)
            )
            row = result.first()
            if row is None:
                return None
            api_token, user = row._tuple()
            if not hmac.compare_digest(api_token.token_hash, digest):
                return None
            api_token.last_used_at = datetime.now(UTC)
            return authed(user)
