"""Shared FastAPI dependency aliases.

Every router re-declared these two ``Annotated`` types; centralize them so the auth
+ session wiring is defined once.
"""

from typing import Annotated

from fastapi import Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.provider import AuthedUser
from app.auth.runtime import current_user
from app.db import get_session

CurrentUser = Annotated[AuthedUser, Depends(current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]

# Path ids are bigints in Postgres, and FastAPI's plain `int` is unbounded, so
# /icons/99999999999999999999 reached asyncpg and came back as "value out of int64
# range" — a 500, and on /icons an unauthenticated one. Out of range now reads as 422,
# which is what an id no row can have deserves.
_INT64_MAX = 2**63 - 1
RowId = Annotated[int, Path(ge=1, le=_INT64_MAX)]
