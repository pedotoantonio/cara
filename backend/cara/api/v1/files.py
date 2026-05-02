"""File upload endpoints — auth, user-scoped."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from cara.api.deps import get_current_user
from cara.models.user import User
from cara.schemas.file import FileOut
from cara.services import files as svc
from cara.store import get_session

router = APIRouter(prefix="/files", tags=["files"])


@router.get("", response_model=list[FileOut])
async def list_my_files(
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> list[FileOut]:
    rows = await svc.list_files(session, user_id=user.id)
    return [FileOut.model_validate(r) for r in rows]


@router.post("", response_model=FileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),  # noqa: B008
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> FileOut:
    blob = await file.read()
    if not blob:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
    try:
        row = await svc.ingest_blob(
            session,
            user_id=user.id,
            filename=file.filename or "untitled",
            mime_type=file.content_type or "application/octet-stream",
            blob=blob,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc)) from exc
    return FileOut.model_validate(row)


@router.get("/{file_id}", response_model=FileOut)
async def get_my_file(
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> FileOut:
    row = await svc.get_file(session, file_id, user_id=user.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    return FileOut.model_validate(row)


@router.get("/{file_id}/download")
async def download_my_file(
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> FileResponse:
    row = await svc.get_file(session, file_id, user_id=user.id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
    return FileResponse(
        path=row.storage_path,
        filename=row.filename,
        media_type=row.mime_type,
    )


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_file(
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),  # noqa: B008
    session: AsyncSession = Depends(get_session),  # noqa: B008
) -> None:
    ok = await svc.delete_file(session, file_id, user_id=user.id)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not found")
