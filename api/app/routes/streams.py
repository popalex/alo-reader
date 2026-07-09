"""Stream entry listing + bounded mark-read (DESIGN.md §5).

A stream is ``all | feed/{id} | folder/{id} | starred`` — the single query
abstraction. Listing is newest-first by id with an exclusive cursor (stable under
concurrent inserts); ``status=unread`` honors ``since_entry_id`` and the per-user
read flag. Search (``q=``) is not implemented yet and is rejected explicitly.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.provider import AuthedUser
from app.auth.runtime import current_user
from app.db import get_session
from app.errors import ApiError
from app.ingest import summarize
from app.store import entries as entries_store
from app.store.entries import SEARCH_LIMIT, SearchRow, StreamRow
from app.store.stream import parse_stream

router = APIRouter(prefix="/streams", tags=["streams"])

CurrentUser = Annotated[AuthedUser, Depends(current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]

MAX_LIMIT = 200


class EntryListItem(BaseModel):
    id: int
    feed_id: int
    feed_title: str
    url: str | None
    title: str
    author: str | None
    summary: str
    published_at: datetime | None
    created_at: datetime
    is_read: bool
    is_starred: bool
    # Highlighted ts_headline excerpt (``<b>`` marks); present only for search (q=).
    snippet: str | None = None


class StreamPage(BaseModel):
    entries: list[EntryListItem]
    next_cursor: str | None


class MarkReadRequest(BaseModel):
    max_entry_id: int


class UpdatedResponse(BaseModel):
    updated: int


def _parse(stream: str) -> str:
    try:
        parse_stream(stream)
    except ValueError as exc:
        raise ApiError(400, "invalid_request", str(exc)) from None
    return stream


def _list_item(row: StreamRow) -> EntryListItem:
    e = row.entry
    return EntryListItem(
        id=e.id,
        feed_id=e.feed_id,
        feed_title=row.feed_title,
        url=e.url,
        title=e.title,
        author=e.author,
        summary=summarize(e.content_html),
        published_at=e.published_at,
        created_at=e.created_at,
        is_read=row.is_read,
        is_starred=row.is_starred,
        snippet=row.snippet if isinstance(row, SearchRow) else None,
    )


@router.get("/{stream:path}/entries", response_model=StreamPage)
async def list_entries(
    stream: str,
    user: CurrentUser,
    session: Session,
    status: Annotated[str, Query(pattern="^(unread|all)$")] = "unread",
    cursor: int | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 50,
    q: str | None = None,
) -> StreamPage:
    parsed = _parse(stream)
    query = q.strip() if q else ""
    if query:
        # Search: chronological (id-desc), stream-scoped, page-capped so ts_headline
        # only runs on the returned rows (DESIGN.md §4.1). websearch_to_tsquery never
        # raises on malformed input, so garbage queries just return few/no results.
        effective_limit = min(limit, SEARCH_LIMIT)
        rows: list[StreamRow] = list(
            await entries_store.search_stream_page(
                session,
                user.id,
                parsed,
                q=query,
                status=status,
                cursor=cursor,
                limit=effective_limit,
            )
        )
    else:
        effective_limit = limit
        rows = await entries_store.list_stream_page(
            session, user.id, parsed, status=status, cursor=cursor, limit=limit
        )
    items = [_list_item(r) for r in rows]
    next_cursor = str(items[-1].id) if len(items) == effective_limit else None
    return StreamPage(entries=items, next_cursor=next_cursor)


@router.post("/{stream:path}/mark-read", response_model=UpdatedResponse)
async def mark_read(
    stream: str, body: MarkReadRequest, user: CurrentUser, session: Session
) -> UpdatedResponse:
    updated = await entries_store.mark_read_bounded(
        session, user.id, _parse(stream), body.max_entry_id
    )
    return UpdatedResponse(updated=updated)
