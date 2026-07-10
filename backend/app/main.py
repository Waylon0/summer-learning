"""
=============================================================================
app/main.py — FastAPI 应用入口
=============================================================================
负责：
  1. 启动时自动创建数据库表、初始化 MinIO 存储桶
  2. 注册请求日志中间件（每个请求都打印详情到终端）
  3. 注册所有 API 路由
  4. 配置 CORS（跨域请求）中间件
  5. 全局异常处理器（捕获自定义异常 → 返回友好错误）
  6. 健康检查端点

启动命令：
  uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
=============================================================================
"""
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from loguru import logger

from app.core.config import get_settings, setup_logging
from app.core.database import engine, Base
from app.core.exceptions import (
    ReimburseBaseException,
    NotFoundException,
    BusinessException,
    ServiceUnavailableException,
    InternalErrorException,
    FileValidationError,
)
from app.core.middleware import RequestLoggingMiddleware, log_error
from app.models import Reimbursement, Invoice, ExpenseItem, DepartmentBudget, ApprovalRecord, User
from app.models import Conversation, ConversationMessage
from app.api.v1.chat import router as chat_router
from app.api.v1.reimbursements import router as reimb_router
from app.api.v1.budget import router as budget_router
from app.api.v1.upload import router as upload_router
from app.api.v1.approval import router as approval_router
from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router
from app.api.v1.stats import router as stats_router
from app.api.v1.invoices import router as invoices_router
from app.api.v1.conversations import router as conversations_router

settings = get_settings()
logger = setup_logging()


# =============================================================================
# 增量 Schema 迁移 (ALTER TABLE ADD COLUMN IF NOT EXISTS)
# =============================================================================
async def _migrate_schema(conn):
    """为已有表添加缺失的列，兼容旧数据库"""
    # 获取引擎 dialect 类型
    dialect_name = engine.dialect.name
    if dialect_name == "sqlite":
        return  # SQLite ALTER ADD COLUMN 不支持 IF NOT EXISTS，但 SQLA create_all 已处理

    import asyncio
    from sqlalchemy import text

    migrations = [
        # invoices 表扩展字段 (发票格式升级)
        ("invoices", "invoice_type", "VARCHAR(32)"),
        ("invoices", "seller_tax_id", "VARCHAR(32)"),
        ("invoices", "buyer_tax_id", "VARCHAR(32)"),
        ("invoices", "tax_amount", "NUMERIC(12, 2) DEFAULT 0"),
        ("invoices", "total_with_tax", "NUMERIC(12, 2)"),
        ("invoices", "expense_item_id", "VARCHAR(36)"),
        # reimbursements 表扩展字段 (费用明细/草稿/差旅上下文)
        ("reimbursements", "title", "VARCHAR(128)"),
        ("reimbursements", "invoice_amount", "NUMERIC(12, 2) DEFAULT 0"),
        ("reimbursements", "subsidy_amount", "NUMERIC(12, 2) DEFAULT 0"),
        ("reimbursements", "trip_destination", "VARCHAR(64)"),
        ("reimbursements", "trip_start_date", "DATE"),
        ("reimbursements", "trip_end_date", "DATE"),
        ("reimbursements", "trip_days", "INTEGER"),
        # reimbursements 表：已开票额 / 可抵扣税额（金额语义细化）
        ("reimbursements", "invoiced_amount", "NUMERIC(12, 2) DEFAULT 0"),
        ("reimbursements", "tax_amount", "NUMERIC(12, 2) DEFAULT 0"),
        # expense_items 表扩展字段（超标说明 / 招待要素 / 外币）
        ("expense_items", "remark", "TEXT"),
        ("expense_items", "attendee_count", "INTEGER"),
        ("expense_items", "guest_info", "VARCHAR(256)"),
        ("expense_items", "currency", "VARCHAR(8) DEFAULT 'CNY'"),
        ("expense_items", "exchange_rate", "NUMERIC(12, 6)"),
        ("expense_items", "original_amount", "NUMERIC(14, 2)"),
    ]
    # 兜底：status 默认值从 pending → draft（新库无所谓，旧库若已有则保留）
    try:
        await conn.execute(text("ALTER TABLE reimbursements ALTER COLUMN status SET DEFAULT 'draft'"))
    except Exception:
        pass

    for table, column, col_type in migrations:
        try:
            await conn.execute(
                text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}")
            )
        except Exception:
            pass  # 列已存在或数据库不支持，跳过

    # 列类型加宽迁移 (ALTER COLUMN TYPE)：
    #   历史表 user_id/approver 为 VARCHAR(32)，但实际存储 36 位 UUID / 长姓名，
    #   会触发 StringDataRightTruncationError。这里将其加宽以兼容旧库。
    alter_types = [
        ("reimbursements", "user_id", "VARCHAR(36)"),
        ("approval_records", "approver", "VARCHAR(64)"),
    ]
    for table, column, col_type in alter_types:
        try:
            await conn.execute(
                text(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {col_type}")
            )
        except Exception:
            pass  # 类型已一致或数据库不支持，跳过

    logger.info("✅ Schema migration checked")
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动与关闭回调"""
    logger.info(f"{'='*60}")
    logger.info(f"  {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"  LLM: {settings.OPENAI_MODEL} @ {settings.OPENAI_BASE_URL}")
    logger.info(f"  API Key: {settings.openai_api_key_masked}")
    logger.info(f"{'='*60}")

    # --- 启动：自动创建数据库表 + 增量迁移 ---
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _migrate_schema(conn)
        logger.info("✅ Database tables ready")
    except Exception as e:
        logger.error(f"❌ Database init failed: {e}")
        db_url = settings.DATABASE_URL
        # 脱敏打印：隐藏密码
        from urllib.parse import urlparse as _urlparse
        parsed = _urlparse(db_url)
        is_sqlite = db_url.startswith("sqlite")
        if is_sqlite:
            logger.error(f"❌ Database init failed ({type(e).__name__}): {e}")
        else:
            host_port = f"{parsed.hostname}:{parsed.port}" if parsed.hostname else "unknown"
            logger.error(f"❌ Database init failed: {e}")
            logger.error(f"💡 请检查:")
            logger.error(f"   1. 数据库地址可访问: {host_port}")
            logger.error(f"   2. PostgreSQL 是否在 {host_port} 上运行")
            logger.error(f"   3. pg_hba.conf 是否允许外部连接 (host all all 0.0.0.0/0 md5)")
            logger.error(f"   4. 防火墙是否放行端口 {parsed.port}")
            logger.error(f"   5. .env 中 DATABASE_URL 是否正确")

    # --- 启动：初始化存储 ---
    try:
        from app.services.ocr_svc import init_minio_bucket, STORAGE_BACKEND
        if STORAGE_BACKEND == "minio":
            init_minio_bucket()
            logger.info("✅ MinIO bucket ready")
        else:
            from pathlib import Path
            upload_dir = Path(settings.UPLOAD_DIR) / "invoices"
            upload_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Local storage ready: {upload_dir}")
    except Exception:
        logger.warning("⚠️  Storage init failed — file upload may be unavailable")

    yield

    # --- 关闭：释放资源 ---
    await engine.dispose()
    logger.info("👋 Shutdown complete")


# =============================================================================
# 创建 FastAPI 应用
# =============================================================================
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    lifespan=lifespan,
)

# =============================================================================
# 中间件注册（注意顺序：先添加的先执行）
# =============================================================================
# 请求日志中间件：记录每个请求的方法、路径、状态码、耗时
app.add_middleware(RequestLoggingMiddleware)

# CORS 中间件：允许前端跨域访问
# allow_origin_regex 覆盖 localhost 及所有 192.168.x.x 局域网地址
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|26\.\d+\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# 全局异常处理器 — 将自定义异常映射为 HTTP 响应
# =============================================================================
@app.exception_handler(ReimburseBaseException)
async def reimburse_exception_handler(request: Request, exc: ReimburseBaseException):
    """
    处理所有项目自定义异常。
    根据异常的 status_code 返回对应的 HTTP 响应。

    响应格式（统一）:
      {
        "error": true,
        "error_code": "NOT_FOUND",
        "message": "报销单不存在: abc-123",
        "detail": {"resource": "报销单", "identifier": "abc-123"}
      }
    """
    elapsed = int((time.perf_counter() - getattr(request.state, "_start_time", time.perf_counter())) * 1000)
    log_error(request, exc, elapsed)

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "error_code": exc.error_code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    兜底异常处理 —— 捕获所有未被上面处理函数覆盖的异常。

    这类异常通常是未预期的 bug，需要记录完整堆栈方便排查。
    """
    elapsed = int((time.perf_counter() - getattr(request.state, "_start_time", time.perf_counter())) * 1000)
    log_error(request, exc, elapsed)
    logger.opt(exception=True).error(f"Unhandled exception on {request.method} {request.url}")

    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "error_code": "INTERNAL_ERROR",
            "message": "服务器内部错误，请稍后重试",
            "detail": {"type": type(exc).__name__},
        },
    )


# =============================================================================
# 注册路由
# =============================================================================
app.include_router(chat_router, prefix="/api/v1")
app.include_router(reimb_router, prefix="/api/v1")
app.include_router(budget_router, prefix="/api/v1")
app.include_router(upload_router, prefix="/api/v1")
app.include_router(approval_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(stats_router, prefix="/api/v1")
app.include_router(invoices_router, prefix="/api/v1")
app.include_router(conversations_router, prefix="/api/v1")


# =============================================================================
# 健康检查
# =============================================================================
@app.get("/health")
async def health_check():
    """健康检查端点 —— 返回服务状态和数据库连通性"""
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(
                Base.metadata.tables["department_budget"].select().limit(1)
            )
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "version": settings.APP_VERSION,
        "database": "connected" if db_ok else "disconnected",
        "llm_model": settings.OPENAI_MODEL,
    }


# =============================================================================
# 文件访问（统一入口：本地磁盘 或 MinIO 均由后端代理，避免暴露 MinIO 地址）
# =============================================================================
@app.get("/api/v1/upload/files/{object_name:path}")
async def serve_local_file(object_name: str):
    """
    提供已上传/生成的文件下载。

    - 本地存储：直接从磁盘读取返回。
    - MinIO 存储：由后端从 MinIO 拉取内容并回传（不返回 MinIO 直链），
      这样队友通过后端 IP 即可下载，无需能访问 MinIO 的 localhost:9000。

    容错：URL 末尾常因 LLM/markdown 文本提取带上多余标点（如 ")"、"）"、","、"。"），
    这里做清洗，避免因一个尾随字符导致"文件不存在"。
    """
    from pathlib import Path as _Path
    from app.core.exceptions import NotFoundException
    from app.services.ocr_svc import STORAGE_BACKEND, get_file_content

    # 清洗尾部易混入的标点/空白（半角与全角）
    cleaned = object_name.strip().rstrip(").，。,、;；)）」』】>》 \t\r\n")
    # 若含 URL 编码的右括号等，也一并去除
    for _suffix in ("%29", "%EF%BC%89"):
        if cleaned.lower().endswith(_suffix.lower()):
            cleaned = cleaned[: -len(_suffix)]
    object_name = cleaned

    # 防路径遍历：object_name 不允许出现上跳
    if ".." in object_name.replace("\\", "/").split("/"):
        raise FileValidationError("非法的文件路径")

    # 内容类型推断
    import mimetypes
    content_type = mimetypes.guess_type(object_name)[0] or "application/octet-stream"
    filename = object_name.rsplit("/", 1)[-1]

    # MinIO 模式：后端代理内容
    if STORAGE_BACKEND == "minio":
        try:
            data = await get_file_content(object_name)
        except Exception:
            raise NotFoundException(resource="文件", identifier=object_name)
        from starlette.responses import Response as _Response
        return _Response(
            content=data,
            media_type=content_type,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    # 本地模式：直接返回磁盘文件
    file_path = (_Path(settings.UPLOAD_DIR) / object_name).resolve()
    base_dir = _Path(settings.UPLOAD_DIR).resolve()
    if not str(file_path).startswith(str(base_dir)):
        raise FileValidationError("非法的文件路径")
    if not file_path.exists():
        raise NotFoundException(resource="文件", identifier=object_name)
    return FileResponse(str(file_path), media_type=content_type)
