import os
import uuid
from minio import Minio
from minio.error import S3Error
from loguru import logger
from app.core.config import get_settings

settings = get_settings()
_client: Minio | None = None


def get_minio_client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )
    return _client


def init_minio_bucket():
    client = get_minio_client()
    if not client.bucket_exists(settings.MINIO_BUCKET):
        client.make_bucket(settings.MINIO_BUCKET)
        logger.info(f"Created MinIO bucket: {settings.MINIO_BUCKET}")


async def upload_file(file_content: bytes, filename: str, content_type: str) -> str:
    from io import BytesIO
    client = get_minio_client()
    ext = os.path.splitext(filename)[1]
    object_name = f"invoices/{uuid.uuid4().hex}{ext}"
    data = BytesIO(file_content)
    client.put_object(
        settings.MINIO_BUCKET,
        object_name,
        data,
        length=len(file_content),
        content_type=content_type,
    )
    logger.info(f"Uploaded: {object_name} ({len(file_content)} bytes)")
    return object_name


async def get_file_url(object_name: str) -> str:
    client = get_minio_client()
    return client.presigned_get_object(settings.MINIO_BUCKET, object_name)
