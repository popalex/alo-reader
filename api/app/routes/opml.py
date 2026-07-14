"""OPML export + import (DESIGN.md §5). Import is synchronous and quota-capped, so
it's bounded; it returns a per-feed report and never merges feeds silently."""

import asyncio
from typing import Annotated
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.provider import AuthedUser
from app.auth.runtime import current_user
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.opml import OpmlFeed, build_opml, parse_opml
from app.routes.subscriptions import normalize_feed_url
from app.store import entries as entries_store
from app.store import feeds as feeds_store
from app.store import folders as folders_store
from app.store import subscriptions as subs_store
from app.store import users as users_store

router = APIRouter(tags=["opml"])

CurrentUser = Annotated[AuthedUser, Depends(current_user)]
Session = Annotated[AsyncSession, Depends(get_session)]


class ImportFailure(BaseModel):
    url: str
    reason: str


class ImportReport(BaseModel):
    imported: int
    skipped: int
    failed: list[ImportFailure]


@router.get("/opml")
async def export_opml(user: CurrentUser, session: Session) -> Response:
    folders = await folders_store.list_all(session, user.id)
    rows = await subs_store.list_with_feed(session, user.id)

    by_folder: dict[int | None, list[OpmlFeed]] = {}
    for sub, feed, _icon in rows:
        by_folder.setdefault(sub.folder_id, []).append(
            OpmlFeed(
                title=sub.title_override or feed.title or feed.feed_url,
                xml_url=feed.feed_url,
                html_url=feed.site_url,
            )
        )

    groups: list[tuple[str | None, list[OpmlFeed]]] = [
        (f.name, by_folder[f.id]) for f in folders if f.id in by_folder
    ]
    if None in by_folder:  # uncategorized feeds at the top level
        groups.append((None, by_folder[None]))

    body = build_opml("alo-reader subscriptions", groups)
    return Response(
        content=body,
        media_type="text/x-opml; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="alo-reader.opml"'},
    )


@router.post("/opml", response_model=ImportReport)
async def import_opml(
    user: CurrentUser, session: Session, file: Annotated[UploadFile, File()]
) -> ImportReport:
    cap = get_settings().opml_max_bytes
    data = await file.read(cap + 1)
    if len(data) > cap:
        raise ApiError(422, "validation_error", f"OPML exceeds {cap} bytes")
    # Reject entity declarations outright (billion-laughs / XXE guard, stdlib-only).
    if b"<!ENTITY" in data.upper():
        raise ApiError(400, "invalid_request", "OPML with entity declarations is not allowed")
    try:
        # ElementTree parse of up to opml_max_bytes is CPU-bound; keep it off the loop.
        parsed = await asyncio.to_thread(parse_opml, data)
    except ElementTree.ParseError:
        raise ApiError(400, "invalid_request", "malformed OPML") from None

    # Serialize the running quota count against concurrent imports/creates (TOCTOU).
    await users_store.lock_row(session, user.id)
    known_folders = {f.name: f for f in await folders_store.list_all(session, user.id)}
    count = await subs_store.count_for_user(session, user.id)
    imported = 0
    skipped = 0
    failed: list[ImportFailure] = []

    for item in parsed:
        try:
            url = normalize_feed_url(item.xml_url)
        except ApiError:
            failed.append(ImportFailure(url=item.xml_url, reason="invalid url"))
            continue
        if count >= user.quota_subs:
            failed.append(ImportFailure(url=url, reason="quota exceeded"))
            continue

        # Seed a new feed's title from the OPML so imported feeds show a name before
        # their first poll (an existing feed keeps its own title).
        feed = await feeds_store.upsert_by_url(session, feed_url=url, title=item.title)
        if await subs_store.get_by_feed(session, user.id, feed.id) is not None:
            skipped += 1
            continue

        folder_id: int | None = None
        if item.folder:
            folder = known_folders.get(item.folder)
            if folder is None:
                folder = await folders_store.create(session, user.id, name=item.folder)
                known_folders[item.folder] = folder
            folder_id = folder.id

        since = await entries_store.max_id_for_feed(session, feed.id)
        await subs_store.create(
            session, user.id, feed_id=feed.id, folder_id=folder_id, since_entry_id=since
        )
        imported += 1
        count += 1

    return ImportReport(imported=imported, skipped=skipped, failed=failed)
