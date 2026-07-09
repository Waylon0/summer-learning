"""
=============================================================================
app/services/ocr_svc.py — 文件存储服务（本地 + MinIO 双模）
=============================================================================
默认使用本地文件系统存储（无需 Docker），可通过 STORAGE_BACKEND=minio 切换。

本文件提供：
  1. upload_file()         — 上传文件
  2. get_file_content()    — 下载文件内容
  3. get_file_url()        — 文件访问 URL
=============================================================================
"""
import os
import uuid
from io import BytesIO
from pathlib import Path
from loguru import logger
from app.core.config import get_settings

settings = get_settings()

STORAGE_BACKEND = settings.STORAGE_BACKEND  # local | minio (从 .env 读取)
LOCAL_UPLOAD_DIR = Path(settings.UPLOAD_DIR).resolve()

# =============================================================================
# MinIO 客户端（仅在 STORAGE_BACKEND=minio 时初始化）
# =============================================================================
_minio_client = None
_minio_available = False


def _get_minio():
    global _minio_client, _minio_available
    if _minio_client is not None:
        return _minio_client
    try:
        from minio import Minio
        _minio_client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
        _minio_available = True
        return _minio_client
    except Exception as e:
        logger.warning(f"MinIO client init failed: {e}")
        _minio_available = False
        return None


def init_minio_bucket():
    """应用启动时调用：MinIO 模式下确保存储桶存在"""
    if STORAGE_BACKEND != "minio":
        return

    client = _get_minio()
    if client is None:
        return

    try:
        if not client.bucket_exists(settings.MINIO_BUCKET):
            client.make_bucket(settings.MINIO_BUCKET)
            logger.info(f"Created MinIO bucket: {settings.MINIO_BUCKET}")
    except Exception as e:
        logger.warning(f"MinIO bucket init failed: {e}")


# =============================================================================
# 文件上传
# =============================================================================
async def upload_file(file_content: bytes, filename: str, content_type: str = "") -> str:
    """
    上传文件，返回存储路径（如 invoices/abc123.pdf）。
    本地模式存到 data/uploads/，MinIO 模式存到远程桶。
    """
    ext = os.path.splitext(filename)[1]
    object_name = f"invoices/{uuid.uuid4().hex}{ext}"

    if STORAGE_BACKEND == "minio" and _minio_available:
        client = _get_minio()
        if client:
            try:
                data = BytesIO(file_content)
                client.put_object(
                    settings.MINIO_BUCKET, object_name,
                    data, length=len(file_content), content_type=content_type,
                )
                logger.info(f"MinIO uploaded: {object_name} ({len(file_content)} bytes)")
                return object_name
            except Exception as e:
                logger.warning(f"MinIO upload failed, falling back to local: {e}")

    # 本地存储
    target = LOCAL_UPLOAD_DIR / object_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(file_content)
    logger.info(f"Local saved: {target} ({len(file_content)} bytes)")
    return object_name


# =============================================================================
# 文件读取
# =============================================================================
async def get_file_content(object_name: str) -> bytes:
    """读取文件二进制内容"""
    if STORAGE_BACKEND == "minio" and _minio_available:
        client = _get_minio()
        if client:
            try:
                response = client.get_object(settings.MINIO_BUCKET, object_name)
                try:
                    return response.read()
                finally:
                    response.close()
                    response.release_conn()
            except Exception as e:
                logger.warning(f"MinIO read failed, trying local: {e}")

    # 本地读取
    target = LOCAL_UPLOAD_DIR / object_name
    if target.exists():
        return target.read_bytes()
    raise FileNotFoundError(f"File not found: {object_name}")


# =============================================================================
# 文件访问 URL
# =============================================================================
async def get_file_url(object_name: str) -> str:
    """
    获取文件访问 URL。

    统一返回【后端相对路径】 /api/v1/upload/files/{object_name}，
    由后端自身代理文件内容（本地磁盘或 MinIO 均可）。

    为什么不直接返回 MinIO 预签名 URL：
      MinIO 预签名 URL 指向 MINIO_ENDPOINT（如 localhost:9000），
      只有运行后端的本机能访问，队友通过后端 IP 连接时打不开。
      改为相对路径后，前端会请求到"后端所在主机"，任何能连上后端的人都能下载。
    """
    return f"/api/v1/upload/files/{object_name}"
