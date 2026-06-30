"""
=============================================================================
app/core/config.py — 全局配置中心
=============================================================================
本文件是整个后端的"配置管家"：
  1. 从 .env 文件和环境变量中读取所有配置参数
  2. 提供统一的配置访问接口 get_settings()
  3. 设置全局日志系统

小白理解：就像遥控器的设置菜单，所有可调参数都在这里集中管理。
=============================================================================
"""
from pydantic_settings import BaseSettings  # 自动从 .env 文件读取配置
from functools import lru_cache               # 缓存函数结果，避免重复创建配置对象
from loguru import logger                     # 优雅的日志库（比 print 强大很多）
import sys
import os


class Settings(BaseSettings):
    """
    配置类 —— 所有运行时参数的定义。
    每个字段如果不传值，就用等号后面的默认值。
    如果在 .env 文件或系统环境变量中设置了同名变量，自动覆盖默认值。
    """

    # ===================== 应用基本信息 =====================
    APP_NAME: str = "ReimburseAgent"            # 应用名称
    APP_VERSION: str = "0.2.0"                  # 版本号
    DEBUG: bool = False                          # 调试模式开关

    # ===================== 数据库配置 =====================
    # 异步数据库连接（asyncpg 是 PostgreSQL 的异步驱动）
    DATABASE_URL: str = "postgresql+asyncpg://reimburse:reimburse123@localhost:5432/reimburse_db"
    # 同步数据库连接（Alembic 迁移工具需要）
    DATABASE_URL_SYNC: str = "postgresql://reimburse:reimburse123@localhost:5432/reimburse_db"

    # ===================== Redis 配置 =====================
    REDIS_URL: str = "redis://localhost:6379/0"              # Redis 主连接（缓存）
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"      # Celery 消息队列（任务调度）
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"  # Celery 结果存储

    # ===================== MinIO 对象存储配置 =====================
    MINIO_ENDPOINT: str = "localhost:9000"                        # MinIO 服务地址
    MINIO_ACCESS_KEY: str = "minioadmin"                           # 访问密钥（用户名）
    MINIO_SECRET_KEY: str = "minioadmin123"                       # 访问密钥（密码）
    MINIO_BUCKET: str = "reimburse-attachments"                   # 存储桶名称（相当于文件夹）
    MINIO_SECURE: bool = False                                     # 是否使用 HTTPS

    # ===================== AI 大模型配置 =====================
    OPENAI_API_KEY: str = "sk-xxx"                                 # API 密钥（需要自己申请）
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"            # API 地址（兼容国产模型）
    OPENAI_MODEL: str = "gpt-4o"                                   # 使用的模型名称

    # ===================== 邮件服务配置 =====================
    SMTP_HOST: str = "smtp.example.com"                            # SMTP 服务器地址
    SMTP_PORT: int = 587                                           # 端口号（587=加密, 25=不加密）
    SMTP_USER: str = ""                                            # 发件人邮箱账号
    SMTP_PASSWORD: str = ""                                        # 发件人邮箱密码或授权码
    SMTP_FROM: str = "noreply@company.com"                         # 发件人显示地址

    # ===================== 其他配置 =====================
    CHROMA_PERSIST_DIR: str = "./data/chroma"     # 向量数据库存储路径（RAG 用，暂未启用）
    UPLOAD_DIR: str = "./data/uploads"             # 上传文件本地暂存路径
    LOG_LEVEL: str = "INFO"                        # 日志级别：DEBUG < INFO < WARNING < ERROR

    # ===================== Pydantic 配置 =====================
    model_config = {
        "env_file": ".env",                 # 自动加载同级目录的 .env 文件
        "env_file_encoding": "utf-8",       # .env 文件的字符编码
        "extra": "ignore",                  # 忽略 .env 中未定义的变量（不会报错）
    }


@lru_cache()
def get_settings() -> Settings:
    """
    获取配置单例。
    @lru_cache 装饰器确保只创建一次 Settings 对象，后续调用直接返回缓存结果。
    这避免了每次请求都重新读取配置文件，提高性能。
    """
    return Settings()


def setup_logging():
    """
    初始化全局日志系统。
    配置两个日志输出通道：
      1. 控制台（stderr）：开发时实时查看，带颜色和格式化
      2. 文件日志：自动按日期分文件，每个文件最大 10MB，保留最近 7 天
    """
    # 移除 loguru 默认的日志处理器
    logger.remove()

    # 控制台输出：带颜色的格式化日志
    logger.add(
        sys.stderr,
        level=get_settings().LOG_LEVEL,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    # 文件输出：详细日志保存到 logs/ 目录，自动轮转
    logger.add(
        "logs/reimburse_{time:YYYY-MM-DD}.log",
        rotation="10 MB",                   # 单文件超过 10MB 自动切分
        retention="7 days",                 # 只保留最近 7 天的日志
        level="DEBUG",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} - "
            "{message}"
        ),
    )
    return logger
