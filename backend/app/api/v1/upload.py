"""
======================================================================
app/api/v1/upload.py — 文件上传 API（增强版）
======================================================================
使用自定义 FileValidationError 代替裸 HTTPException。
======================================================================
"""
import os
import re
from fastapi import APIRouter, UploadFile, File
from loguru import logger

from app.core.config import get_settings
from app.core.exceptions import FileValidationError, StorageServiceError
from app.services.ocr_svc import upload_file as upload_to_minio

router = APIRouter(prefix="/upload", tags=["upload"])

settings = get_settings()
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _sanitize_filename(filename: str) -> str:
    """过滤文件名中的危险字符，防止路径遍历"""
    name = os.path.basename(filename) or "invoice.pdf"
    name = re.sub(r'[^\w\s.\-()\u4e00-\u9fff]', '_', name)
    return name or "invoice.pdf"


@router.post("")
async def upload_invoice(file: UploadFile = File(..., max_length=MAX_FILE_SIZE)):
    """上传发票/票据文件到 MinIO"""
    safe_filename = _sanitize_filename(file.filename or "invoice.pdf")

    # --- 步骤1：扩展名校验 ---
    ext = os.path.splitext(safe_filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"不支持的文件类型: {ext}，仅支持 {ALLOWED_EXTENSIONS}"
        )

    # --- 步骤2：读取并上传 ---
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise FileValidationError(
            f"文件大小 ({len(content) / 1024 / 1024:.1f}MB) 超过 10MB 限制"
        )

    try:
        object_name = await upload_to_minio(
            content,
            safe_filename,
            file.content_type or "application/octet-stream",
        )
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise StorageServiceError(detail=str(e))

    logger.info(f"文件上传成功: {safe_filename} → {object_name} ({len(content)} bytes)")

    return {
        "filename": safe_filename,
        "object_name": object_name,
        "size": len(content),
        "status": "uploaded",
    }
