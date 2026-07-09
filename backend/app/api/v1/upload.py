"""
======================================================================
app/api/v1/upload.py — 文件上传 API
======================================================================
双层校验：扩展名 + magic bytes 防伪装攻击。
======================================================================
"""
import os
import re

from fastapi import APIRouter, UploadFile, File, Depends
from loguru import logger

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.exceptions import FileValidationError, StorageServiceError
from app.services.ocr_svc import upload_file as upload_to_storage
from app.models.user import User

router = APIRouter(prefix="/upload", tags=["upload"])

settings = get_settings()
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024

# Magic bytes 签名
MAGIC_SIGNATURES = {
    b"\x89PNG\r\n\x1a\n": ".png",
    b"\xff\xd8\xff": ".jpg",
    b"RIFF": ".webp",  # webp: RIFF....WEBP
    b"%PDF": ".pdf",
}


def _check_magic_bytes(content: bytes, claimed_ext: str) -> bool:
    """通过文件头 magic bytes 校验真实类型，防止扩展名伪装"""
    if claimed_ext in (".jpg", ".jpeg"):
        return content[:3] == b"\xff\xd8\xff"
    if claimed_ext == ".png":
        return content[:8] == b"\x89PNG\r\n\x1a\n"
    if claimed_ext == ".webp":
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    if claimed_ext == ".pdf":
        return content[:4] == b"%PDF"
    return False


def _sanitize_filename(filename: str) -> str:
    """过滤文件名中的危险字符，防止路径遍历"""
    name = os.path.basename(filename) or "invoice.pdf"
    name = re.sub(r'[^\w\s.\-()\u4e00-\u9fff]', '_', name)
    return name or "invoice.pdf"


@router.post("")
async def upload_invoice(
    file: UploadFile = File(..., max_length=MAX_FILE_SIZE),
    user: User = Depends(get_current_user),
):
    """上传发票/票据文件（需登录）"""
    safe_filename = _sanitize_filename(file.filename or "invoice.pdf")

    # --- 步骤1：扩展名校验 ---
    ext = os.path.splitext(safe_filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"不支持的文件类型: {ext}，仅支持 {ALLOWED_EXTENSIONS}"
        )

    # --- 步骤2：读取内容 ---
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise FileValidationError(
            f"文件大小 ({len(content) / 1024 / 1024:.1f}MB) 超过 10MB 限制"
        )

    # --- 步骤3：magic bytes 校验 ---
    if not _check_magic_bytes(content, ext):
        raise FileValidationError(
            f"文件内容与扩展名 {ext} 不匹配，文件可能已损坏或类型伪装"
        )

    # --- 步骤4：上传 ---
    try:
        object_name = await upload_to_storage(
            content,
            safe_filename,
            file.content_type or "application/octet-stream",
        )
    except Exception as e:
        logger.error(f"文件上传失败: {e}")
        raise StorageServiceError(detail=str(e))

    logger.info(f"文件上传成功: {safe_filename} → {object_name} ({len(content)} bytes) by {user.username}")

    return {
        "filename": safe_filename,
        "object_name": object_name,
        "size": len(content),
        "status": "uploaded",
    }
