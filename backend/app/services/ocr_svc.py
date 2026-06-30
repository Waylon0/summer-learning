"""
=============================================================================
app/services/ocr_svc.py — 文件存储服务（MinIO）
=============================================================================
MinIO 是一个"自建版 AWS S3"，用于存储报销相关的文件（发票图片、生成的 PDF 等）。

本文件提供：
  1. get_minio_client()    — 获取 MinIO 连接客户端（单例模式）
  2. init_minio_bucket()   — 首次启动时自动创建存储桶
  3. upload_file()         — 上传文件到 MinIO
  4. get_file_url()        — 生成文件的临时下载链接

小白理解：
  MinIO = "云盘"，bucket = "文件夹"，object = "文件"
=============================================================================
"""
import os
import uuid
from io import BytesIO                            # 把 bytes 数据包装成"文件对象"
from minio import Minio
from minio.error import S3Error
from loguru import logger
from app.core.config import get_settings

settings = get_settings()

# =============================================================================
# 全局变量：MinIO 客户端单例
# =============================================================================
# 只创建一个客户端对象，所有请求共享（节省资源）
_client: Minio | None = None


def get_minio_client() -> Minio:
    """获取 MinIO 客户端（单例模式：全局只创建一次）"""
    global _client
    if _client is None:
        # 第一次调用时才创建连接
        _client = Minio(
            settings.MINIO_ENDPOINT,               # 服务器地址（如 localhost:9000）
            access_key=settings.MINIO_ACCESS_KEY,  # 相当于"用户名"
            secret_key=settings.MINIO_SECRET_KEY,  # 相当于"密码"
            secure=settings.MINIO_SECURE,          # 是否 HTTPS
        )
    return _client


def init_minio_bucket():
    """应用启动时调用：确保存储桶存在，不存在则创建"""
    client = get_minio_client()
    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)
        logger.info(f"Created MinIO bucket: {settings.MINIO_BUCKET}")


async def upload_file(file_content: bytes, filename: str, content_type: str) -> str:
    """
    上传文件到 MinIO。

    参数:
        file_content : 文件的二进制内容
        filename     : 原始文件名（用于提取扩展名）
        content_type : MIME 类型（如 application/pdf）

    返回: MinIO 中的对象路径（如 invoices/abc123.pdf）

    流程：
      1. 从原始文件名提取扩展名（.pdf/.png 等）
      2. 生成唯一对象名 = invoices/ + 随机 UUID + 扩展名（避免重名覆盖）
      3. 调用 put_object 上传
    """
    client = get_minio_client()

    # 提取扩展名
    ext = os.path.splitext(filename)[1]              # "发票.pdf" → ".pdf"
    # 生成唯一路径
    object_name = f"invoices/{uuid.uuid4().hex}{ext}"  # 如 invoices/a1b2c3d4e5f6.pdf

    # BytesIO 把 bytes 包装成"文件对象"，MinIO 需要这种格式
    data = BytesIO(file_content)
    client.put_object(
        settings.MINIO_BUCKET,
        object_name,
        data,
        length=len(file_content),                    # 必须指定长度
        content_type=content_type,
    )
    logger.info(f"Uploaded: {object_name} ({len(file_content)} bytes)")
    return object_name


async def get_file_url(object_name: str) -> str:
    """生成文件的临时下载链接（7天有效）"""
    client = get_minio_client()
    return client.presigned_get_object(settings.MINIO_BUCKET, object_name)
