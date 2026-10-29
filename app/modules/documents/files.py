"""Generic photo/file upload used by every capture flow. Images are compressed in the browser first."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.core.deps import get_current_user
from app.core.storage import save_bytes

router = APIRouter(prefix="/files", tags=["files"], dependencies=[Depends(get_current_user)])

MAX_BYTES = 8 * 1024 * 1024


@router.post("", status_code=201)
async def upload_file(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File too large (max 8 MB). Photos are compressed in the app before upload.")
    if not data:
        raise HTTPException(422, "Empty file")
    return await save_bytes(data, file.filename or "upload", file.content_type or "application/octet-stream")
