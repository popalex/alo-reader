"""Shared FastAPI dependency aliases.

Every router re-declared these two ``Annotated`` types; centralize them so the auth
+ session wiring is defined once.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.provider import AuthedUser
from app.auth.runtime import current_user
from app.db import get_session

CurrentUser = Annotated[AuthedUser, Depends(current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]
