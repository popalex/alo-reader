"""Exact unread counts (DESIGN.md §5, §4). Index-backed, no counters."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.deps import CurrentUser, Session
from app.store.counts import unread_counts

router = APIRouter(tags=["counts"])


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
