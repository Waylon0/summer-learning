"""
=============================================================================
app/main.py — FastAPI 应用入口
=============================================================================
这是整个后端的"大门"，负责：
  1. 启动时自动创建数据库表、初始化 MinIO 存储桶
  2. 注册所有 API 路由
  3. 配置 CORS（跨域请求）中间件
  4. 全局异常捕获
  5. 健康检查端点

启动命令：
  uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
=============================================================================
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware       # 允许前端跨域访问
from fastapi.responses import JSONResponse               # JSON 格式响应
from loguru import logger

from app.core.config import get_settings, setup_logging
from app.core.database import engine, Base               # 数据库引擎和 ORM 基类
from app.models import Reimbursement, Invoice, DepartmentBudget, ApprovalRecord  # 导入所有模型（确保 Base 能发现它们）
from app.api.v1.chat import router as chat_router
from app.api.v1.reimbursements import router as reimb_router
from app.api.v1.budget import router as budget_router
from app.api.v1.upload import router as upload_router
from app.api.v1.approval import router as approval_router

settings = get_settings()
logger = setup_logging()                                  # 初始化日志系统


# =============================================================================
# 生命周期管理
# =============================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用启动和关闭时的回调。

    启动时：
      1. 自动创建所有数据库表（如果还没创建的话）
      2. 初始化 MinIO 存储桶

    关闭时：
      1. 释放数据库连接池
    """
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} starting...")

    # --- 启动：自动建表 ---
    # Base.metadata.create_all 会检查所有继承自 Base 的类，
    # 如果对应的表不存在，自动创建。
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables verified")

    # --- 启动：初始化 MinIO ---
    from app.services.ocr_svc import init_minio_bucket
    try:
        init_minio_bucket()
        logger.info("✅ MinIO bucket ready")
    except Exception:
        logger.warning("⚠️  MinIO not available (file upload disabled)")

    yield  # ← 在这里等待应用运行...

    # --- 关闭：清理资源 ---
    await engine.dispose()
    logger.info("👋 Shutdown complete")


# =============================================================================
# 创建 FastAPI 应用实例
# =============================================================================
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",                                     # Swagger UI 文档地址
    lifespan=lifespan,
)

# =============================================================================
# CORS 中间件 —— 允许前端跨域请求
# =============================================================================
# 前后端分离时，前端（localhost:3000）和后端（localhost:8000）是不同的"域"。
# 浏览器默认禁止跨域请求，CORS 中间件告诉浏览器"这几个域是可信的"。
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",                         # React 开发服务器
        "http://127.0.0.1:3000",
        "http://localhost:5173",                         # Vite 默认端口
    ],
    allow_credentials=True,                              # 允许携带 Cookie
    allow_methods=["*"],                                 # 允许所有 HTTP 方法
    allow_headers=["*"],                                 # 允许所有请求头
)


# =============================================================================
# 全局异常处理
# =============================================================================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    兜底的异常处理函数。
    任何未被捕获的异常都会到这里，返回 500 错误和详细信息。
    这样前端至少能收到一个有意义的错误信息，而不是空白页面。
    """
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "path": str(request.url)},
    )


# =============================================================================
# 注册路由
# =============================================================================
# 所有 API 都挂载在 /api/v1 前缀下
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
    """
    健康检查端点 —— 运维监控用。

    返回示例：
      {"status": "ok", "version": "0.2.0", "database": "connected"}

    如果数据库连不上，status 会变成 "degraded"。
    """
    db_ok = True
    try:
        # 尝试查询 department_budget 表来验证数据库连接
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
    }
