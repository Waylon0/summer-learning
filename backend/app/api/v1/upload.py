import os
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.config import get_settings
from app.services.ocr_svc import upload_file as upload_to_minio

router = APIRouter(prefix="/upload", tags=["upload"])

settings = get_settings()
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


@router.post("")
async def upload_invoice(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "invoice.pdf")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}，仅支持 {ALLOWED_EXTENSIONS}")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件大小不能超过 10MB")

    object_name = await upload_to_minio(content, file.filename, file.content_type or "application/octet-stream")

    return {
        "filename": file.filename,
        "object_name": object_name,
        "size": len(content),
        "status": "uploaded",
    }
