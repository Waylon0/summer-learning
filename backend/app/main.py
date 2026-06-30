from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.core.config import get_settings, setup_logging
from app.core.database import engine, Base
from app.models import Reimbursement, Invoice, DepartmentBudget, ApprovalRecord
from app.api.v1.chat import router as chat_router
from app.api.v1.reimbursements import router as reimb_router
from app.api.v1.budget import router as budget_router
from app.api.v1.upload import router as upload_router
from app.api.v1.approval import router as approval_router

settings = get_settings()
logger = setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} starting...")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables verified")

    from app.services.ocr_svc import init_minio_bucket
    try:
        init_minio_bucket()
        logger.info("✅ MinIO bucket ready")
    except Exception:
        logger.warning("⚠️  MinIO not available (file upload disabled)")

    yield

    await engine.dispose()
    logger.info("👋 Shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    lifespan=lifespan,
)

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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "path": str(request.url)},
    )


app.include_router(chat_router, prefix="/api/v1")
app.include_router(reimb_router, prefix="/api/v1")
app.include_router(budget_router, prefix="/api/v1")
app.include_router(upload_router, prefix="/api/v1")
app.include_router(approval_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(Base.metadata.tables["department_budget"].select().limit(1))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "version": settings.APP_VERSION,
        "database": "connected" if db_ok else "disconnected",
    }
