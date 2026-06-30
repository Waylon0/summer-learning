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
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.config import get_settings, setup_logging
from app.core.database import engine, Base
from app.core.exceptions import (
    ReimburseBaseException,
    NotFoundException,
    BusinessException,
    ServiceUnavailableException,
    InternalErrorException,
)
from app.core.middleware import RequestLoggingMiddleware, log_error
from app.models import Reimbursement, Invoice, DepartmentBudget, ApprovalRecord
from app.api.v1.chat import router as chat_router
from app.api.v1.reimbursements import router as reimb_router
from app.api.v1.budget import router as budget_router
from app.api.v1.upload import router as upload_router
from app.api.v1.approval import router as approval_router

settings = get_settings()
logger = setup_logging()


# =============================================================================
# 生命周期管理
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动与关闭回调"""
    logger.info(f"{'='*60}")
    logger.info(f"  {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"  LLM: {settings.OPENAI_MODEL} @ {settings.OPENAI_BASE_URL}")
    logger.info(f"{'='*60}")

    # --- 启动：自动创建数据库表 ---
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Database tables ready")
    except Exception as e:
        logger.error(f"❌ Database init failed: {e}")

    # --- 启动：初始化 MinIO 存储桶 ---
    try:
        from app.services.ocr_svc import init_minio_bucket
        init_minio_bucket()
        logger.info("✅ MinIO bucket ready")
    except Exception:
        logger.warning("⚠️  MinIO not available — file upload disabled")

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
    ],
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
