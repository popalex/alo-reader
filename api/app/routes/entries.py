"""Single-entry read + per-user state writes (DESIGN.md §5).

``GET /entries/{id}`` returns the full sanitized ``content_html`` for an entry the
user can see (in a subscribed feed); another tenant's id reads as 404.
``POST /entries/state`` is the idempotent, offline-replayable state writer.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.provider import AuthedUser
from app.auth.runtime import current_user
from app.db import get_session
from app.errors import ApiError
from app.store import entries as entries_store
from app.store import entry_states as states_store

router = APIRouter(tags=["entries"])

CurrentUser = Annotated[AuthedUser, Depends(current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]

MAX_STATE_IDS = 1000


class EntryDetail(BaseModel):
    id: int
    feed_id: int
    feed_title: str
    url: str | None
    title: str
    author: str | None
    summary: str
    content_html: str
    published_at: datetime | None
    created_at: datetime
    is_read: bool
    is_starred: bool


class StateRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_STATE_IDS)
    read: bool | None = None
    starred: bool | None = None
    changed_at: datetime | None = None


class UpdatedResponse(BaseModel):
    updated: int


@router.get("/entries/{entry_id}", response_model=EntryDetail)
async def get_entry(entry_id: int, user: CurrentUser, session: Session) -> EntryDetail:
    row = await entries_store.get_for_user(session, user.id, entry_id)
    if row is None:
        raise ApiError(404, "not_found", "entry not found")
    e = row.entry
    return EntryDetail(
        id=e.id,
        feed_id=e.feed_id,
        feed_title=row.feed_title,
        url=e.url,
        title=e.title,
        author=e.author,
        summary=e.summary,
        content_html=e.content_html,
        published_at=e.published_at,
        created_at=e.created_at,
        is_read=row.is_read,
        is_starred=row.is_starred,
    )


@router.post("/entries/state", response_model=UpdatedResponse)
async def set_state(body: StateRequest, user: CurrentUser, session: Session) -> UpdatedResponse:
    if body.read is None and body.starred is None:
        raise ApiError(422, "validation_error", "at least one of read/starred is required")
    changed_at = body.changed_at or datetime.now(UTC)
    updated = await states_store.apply_state_batch(
        session,
        user.id,
        body.ids,
        is_read=body.read,
        is_starred=body.starred,
        changed_at=changed_at,
    )
    return UpdatedResponse(updated=updated)
