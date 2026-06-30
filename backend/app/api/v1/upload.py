"""
=============================================================================
app/api/v1/upload.py — 文件上传 API
=============================================================================
POST /api/v1/upload — 上传发票/票据文件到 MinIO

安全限制：
  - 仅允许: PDF / PNG / JPG / JPEG / WebP
  - 单文件最大 10MB
=============================================================================
"""
import os
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.config import get_settings
from app.services.ocr_svc import upload_file as upload_to_minio  # 重命名避免冲突

router = APIRouter(prefix="/upload", tags=["upload"])

settings = get_settings()

# 允许的文件扩展名（白名单，不在名单内的一律拒绝）
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


@router.post("")
async def upload_invoice(file: UploadFile = File(...)):
    """
    上传发票/票据文件。

    步骤：
      1. 检查文件扩展名（防病毒、防恶意文件）
      2. 检查文件大小（>10MB 拒绝）
      3. 上传到 MinIO 对象存储
      4. 返回存储路径
    """
    # --- 步骤1：扩展名校验 ---
    # os.path.splitext("发票.pdf") → ("发票", ".pdf")
    ext = os.path.splitext(file.filename or "invoice.pdf")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}，仅支持 {ALLOWED_EXTENSIONS}"
        )

    # --- 步骤2：读取文件并检查大小 ---
    content = await file.read()                            # 读取整个文件到内存
    if len(content) > 10 * 1024 * 1024:                    # 10MB = 10 * 1024 * 1024 字节
        raise HTTPException(status_code=400, detail="文件大小不能超过 10MB")

    # --- 步骤3：上传到 MinIO ---
    object_name = await upload_to_minio(
        content,
        file.filename,
        file.content_type or "application/octet-stream"    # 如果前端没传 MIME 类型，用通用类型
    )

    # --- 步骤4：返回结果 ---
    return {
        "filename": file.filename,
        "object_name": object_name,                        # MinIO 中的路径
        "size": len(content),                              # 文件大小（字节）
        "status": "uploaded",
    }
