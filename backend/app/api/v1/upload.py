"""
=============================================================================
app/api/v1/upload.py — 文件上传 API（增强版）
=============================================================================
使用自定义 FileValidationError 代替裸 HTTPException。
=============================================================================
"""
import os
from fastapi import APIRouter, UploadFile, File
from loguru import logger

from app.core.config import get_settings
from app.core.exceptions import FileValidationError, StorageServiceError
from app.services.ocr_svc import upload_file as upload_to_minio

router = APIRouter(prefix="/upload", tags=["upload"])

settings = get_settings()
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


@router.post("")
async def upload_invoice(file: UploadFile = File(...)):
    """上传发票/票据文件到 MinIO"""
    # --- 步骤1：扩展名校验 ---
    ext = os.path.splitext(file.filename or "invoice.pdf")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"不支持的文件类型: {ext}，仅支持 {ALLOWED_EXTENSIONS}"
        )

    # --- 步骤2：大小校验 ---
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise FileValidationError(
            f"文件大小 ({len(content) / 1024 / 1024:.1f}MB) 超过 10MB 限制"
        )

    # --- 步骤3：上传 ---
    try:
        object_name = await upload_to_minio(
            content,
            file.filename,
            file.content_type or "application/octet-stream",
        )
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise StorageServiceError(detail=str(e))

    logger.info(f"文件上传成功: {file.filename} → {object_name} ({len(content)} bytes)")

    return {
        "filename": file.filename,
        "object_name": object_name,
        "size": len(content),
        "status": "uploaded",
    }
