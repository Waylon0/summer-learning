from pydantic_settings import BaseSettings
from functools import lru_cache
from loguru import logger
import sys
import os


class Settings(BaseSettings):
    APP_NAME: str = "ReimburseAgent"
    APP_VERSION: str = "0.2.0"
    DEBUG: bool = False

    DATABASE_URL: str = "postgresql+asyncpg://reimburse:reimburse123@localhost:5432/reimburse_db"
    DATABASE_URL_SYNC: str = "postgresql://reimburse:reimburse123@localhost:5432/reimburse_db"

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_BUCKET: str = "reimburse-attachments"
    MINIO_SECURE: bool = False

    OPENAI_API_KEY: str = "sk-xxx"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o"

    SMTP_HOST: str = "smtp.example.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@company.com"

    CHROMA_PERSIST_DIR: str = "./data/chroma"
    UPLOAD_DIR: str = "./data/uploads"

    LOG_LEVEL: str = "INFO"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def setup_logging():
    logger.remove()
    logger.add(
        sys.stderr,
        level=get_settings().LOG_LEVEL,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    )
    logger.add(
        "logs/reimburse_{time:YYYY-MM-DD}.log",
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
    )
    return logger
