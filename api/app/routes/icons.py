"""Serve stored favicons (DESIGN.md §5). Icons are global, immutable, and public
(referenced from <img> tags), so they carry long-lived cache headers and skip auth."""

from fastapi import APIRouter
from fastapi.responses import Response

from app.deps import Session
from app.errors import ApiError
from app.store import icons as icons_store

router = APIRouter(tags=["icons"])

# One year, immutable — an icon id maps to fixed bytes forever.
_CACHE_CONTROL = "public, max-age=31536000, immutable"


@router.get("/icons/{icon_id}")
async def get_icon(icon_id: int, session: Session) -> Response:
    icon = await icons_store.get(session, icon_id)
    if icon is None or icon.data is None:
        raise ApiError(404, "not_found", "icon not found")
    return Response(
        content=icon.data,
        media_type=icon.mime or "image/x-icon",
        headers={"Cache-Control": _CACHE_CONTROL},
    )
