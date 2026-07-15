"""Folder CRUD (DESIGN.md §5). All endpoints are tenant-scoped: another user's
folder id is indistinguishable from a missing one (404, never 403)."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.deps import CurrentUser, Session
from app.errors import ApiError
from app.models import Folder
from app.store import folders as folders_store

router = APIRouter(prefix="/folders", tags=["folders"])


class FolderResponse(BaseModel):
    id: int
    name: str
    position: int


class CreateFolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    position: int = 0


class UpdateFolderRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    position: int | None = None


def _shape(folder: Folder) -> FolderResponse:
    return FolderResponse(id=folder.id, name=folder.name, position=folder.position)


@router.get("", response_model=list[FolderResponse])
async def list_folders(user: CurrentUser, session: Session) -> list[FolderResponse]:
    return [_shape(f) for f in await folders_store.list_all(session, user.id)]


@router.post("", response_model=FolderResponse, status_code=201)
async def create_folder(
    body: CreateFolderRequest, user: CurrentUser, session: Session
) -> FolderResponse:
    folder = await folders_store.create(session, user.id, name=body.name, position=body.position)
    return _shape(folder)


@router.patch("/{folder_id}", response_model=FolderResponse)
async def update_folder(
    folder_id: int, body: UpdateFolderRequest, user: CurrentUser, session: Session
) -> FolderResponse:
    folder = await folders_store.update(
        session, user.id, folder_id, name=body.name, position=body.position
    )
    if folder is None:
        raise ApiError(404, "not_found", "folder not found")
    return _shape(folder)


@router.delete("/{folder_id}", status_code=204)
async def delete_folder(folder_id: int, user: CurrentUser, session: Session) -> None:
    # Non-destructive: the subscriptions.folder_id FK is ON DELETE SET NULL, so a
    # deleted category's feeds simply fall back to Uncategorized.
    if not await folders_store.delete(session, user.id, folder_id):
        raise ApiError(404, "not_found", "folder not found")
