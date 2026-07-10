"""
=============================================================================
app/core/config.py — 全局配置中心
=============================================================================
本文件是整个后端的"配置管家"：
  1. 从 .env 文件和环境变量中读取所有配置参数
  2. 提供统一的配置访问接口 get_settings()
  3. 设置全局日志系统

设计说明（v2.1 起）：
  之前使用 `pydantic_settings.BaseSettings` 自动读取 .env。但某些
  `pydantic-settings` 版本在导入时会**无条件** `from dotenv import dotenv_values`，
  一旦 `python-dotenv` 缺失/损坏（如错误的版本 wheel、子进程环境不一致），
  会导致 `import pydantic_settings` 直接失败、后端无法启动。

  为彻底摆脱这一脆弱依赖，这里改用**普通 pydantic BaseModel + 内置 .env 解析**：
  - 不再依赖 pydantic-settings / python-dotenv 即可读取配置；
  - 优先级：进程环境变量 os.environ > 项目 .env 文件 > 字段默认值；
  - 行为与原来保持一致（同名大写 KEY、类型自动转换、忽略未知键）。
=============================================================================
"""
from pydantic import BaseModel                    # 仅用核心 pydantic，无需 pydantic-settings
from functools import lru_cache                    # 缓存函数结果，避免重复创建配置对象
from pathlib import Path
from loguru import logger                          # 优雅的日志库（比 print 强大很多）
import sys
import os


class Settings(BaseModel):
    """
    配置类 —— 所有运行时参数的定义。
    每个字段如果不传值，就用等号后面的默认值；
    若在 .env 文件或系统环境变量中设置了同名（大写）变量，则自动覆盖默认值。
    """

    # pydantic v2：忽略未知字段（.env 里的额外键不会报错）
    model_config = {"extra": "ignore"}

    # ===================== 应用基本信息 =====================
    APP_NAME: str = "ReimburseAgent"            # 应用名称
    APP_VERSION: str = "0.2.0"                  # 版本号
    DEBUG: bool = False                          # 调试模式开关

    # 公司全称（发票抬头/购买方校验用）
    COMPANY_NAME: str = "中国石油华东分公司"
    # 发票有效期（天）：开票日期距报销日超过该天数视为过期（软性提示）
    INVOICE_MAX_AGE_DAYS: int = 90

    # ===================== 数据库配置 =====================
    DATABASE_URL: str = "postgresql+asyncpg://reimburse:reimburse123@localhost:5432/reimburse_db"
    DATABASE_URL_SYNC: str = "postgresql://reimburse:reimburse123@localhost:5432/reimburse_db"

    # ===================== Redis 配置 =====================
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ===================== MinIO 对象存储配置 =====================
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_BUCKET: str = "reimburse-attachments"
    MINIO_SECURE: bool = False

    # ===================== AI 大模型配置 =====================
    OPENAI_API_KEY: str = "sk-xxx"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o"

    # ===================== 邮件服务配置 =====================
    SMTP_HOST: str = "smtp.example.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@company.com"

    # ===================== 存储配置 =====================
    STORAGE_BACKEND: str = "local"
    CHROMA_PERSIST_DIR: str = "./data/chroma"
    UPLOAD_DIR: str = "./data/uploads"
    LOG_LEVEL: str = "INFO"

    # ===================== 安全配置 =====================
    # JWT 密钥：优先从环境变量 / .env 读取，避免在源码中写死真实密钥。
    # 若未配置则使用带 "INSECURE" 标记的开发占位符，并在启动时告警。
    JWT_SECRET_KEY: str = "INSECURE-DEV-KEY-please-set-JWT_SECRET_KEY-in-env"

    # ===================== NLP / 意图理解配置 =====================
    # 中文语义 embedding 后端: auto | sentence_transformers | chromadb | none
    EMBEDDING_BACKEND: str = "auto"
    # 本地中文向量模型路径或名称（如 shibing624/text2vec-base-chinese 或本地目录）
    EMBEDDING_MODEL: str = "shibing624/text2vec-base-chinese"
    # 语义路由采纳阈值：最高相似度 ≥ 此值才直接采纳语义结果
    INTENT_SEMANTIC_THRESHOLD: float = 0.72
    # LLM 意图置信度阈值：≥ 此值直接信任 LLM 结果
    INTENT_LLM_TRUST_THRESHOLD: float = 0.75

    @property
    def openai_api_key_masked(self) -> str:
        """返回脱敏后的 API Key，安全用于日志输出"""
        key = self.OPENAI_API_KEY
        if len(key) <= 8:
            return "***"
        return key[:4] + "****" + key[-4:]


# =============================================================================
# .env 解析（内置，不依赖 python-dotenv）
# =============================================================================
def _find_env_file() -> Path | None:
    """定位 backend/.env（相对本文件），退而求其次用当前工作目录的 .env。"""
    # config.py 位于 backend/app/core/ → parents[2] 即 backend/
    candidate = Path(__file__).resolve().parents[2] / ".env"
    if candidate.exists():
        return candidate
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return cwd_env
    return None


def _read_env_file(path: Path) -> dict[str, str]:
    """极简 .env 解析：忽略空行/注释行；按第一个 '=' 切分；去除值两侧引号。"""
    data: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8-sig")  # utf-8-sig 兼容 BOM
    except (OSError, UnicodeDecodeError):
        return data
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if key:
            data[key] = val
    return data


@lru_cache()
def get_settings() -> Settings:
    """
    获取配置单例。
    @lru_cache 确保只创建一次 Settings 对象。
    取值优先级：os.environ > .env 文件 > 字段默认值。
    """
    file_vals: dict[str, str] = {}
    env_path = _find_env_file()
    if env_path is not None:
        file_vals = _read_env_file(env_path)

    values: dict[str, object] = {}
    for name in Settings.model_fields:
        if name in os.environ:
            values[name] = os.environ[name]        # 进程环境变量优先
        elif name in file_vals:
            values[name] = file_vals[name]          # 其次 .env 文件
        # 否则交给字段默认值
    # pydantic v2 会把字符串按字段类型自动转换（int/bool/float 等）
    return Settings(**values)


def setup_logging():
    """
    初始化全局日志系统。
    配置两个日志输出通道：
      1. 控制台（stdout）：开发时实时查看，带颜色和格式化
      2. 文件日志：自动按日期分文件，每个文件最大 10MB，保留最近 7 天

    实时性说明：
      控制台 sink 使用 stdout（uvicorn 默认也走 stdout，行缓冲更利于终端实时显示），
      并显式 colorize=True。若通过管道/重定向运行导致块缓冲，可用环境变量
      PYTHONUNBUFFERED=1 强制无缓冲。
    """
    # 移除 loguru 默认的日志处理器
    logger.remove()

    # Windows 控制台默认 GBK 编码，无法输出 emoji（✅📄📧 等），
    # 会抛 UnicodeEncodeError 导致该条日志"消失"。这里强制把标准输出/错误
    # 重配为 UTF-8，保证含 emoji 的日志也能正常打印到终端。
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    # 控制台输出：带颜色的格式化日志（实时刷新到终端）
    logger.add(
        sys.stdout,
        level=get_settings().LOG_LEVEL,
        colorize=True,
        enqueue=False,      # 同步写出，保证请求日志即时出现在终端
        backtrace=False,
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
        encoding="utf-8",
        enqueue=False,
        format=(
            "{time:YYYY-MM-DD HH:mm:ss.SSS} | "
            "{level: <8} | "
            "{name}:{function}:{line} - "
            "{message}"
        ),
    )
    return logger
