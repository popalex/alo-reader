"""Exact unread counts (DESIGN.md §5, §4). Index-backed, no counters."""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.provider import AuthedUser
from app.auth.runtime import current_user
from app.db import get_session
from app.store.counts import unread_counts

router = APIRouter(tags=["counts"])

CurrentUser = Annotated[AuthedUser, Depends(current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]


class SubscriptionUnread(BaseModel):
    id: int
    unread: int


class CountsResponse(BaseModel):
    total_unread: int
    subscriptions: list[SubscriptionUnread]


@router.get("/counts", response_model=CountsResponse)
async def get_counts(user: CurrentUser, session: Session) -> CountsResponse:
    counts = await unread_counts(session, user.id)
    return CountsResponse(
        total_unread=counts.total,
        subscriptions=[
            SubscriptionUnread(id=sub_id, unread=n) for sub_id, n in counts.per_subscription.items()
        ],
    )
