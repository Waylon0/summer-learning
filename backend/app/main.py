from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.api.v1.chat import router as chat_router
from app.api.v1.reimbursements import router as reimb_router
from app.api.v1.budget import router as budget_router
from app.api.v1.upload import router as upload_router
from app.api.v1.approval import router as approval_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api/v1")
app.include_router(reimb_router, prefix="/api/v1")
app.include_router(budget_router, prefix="/api/v1")
app.include_router(upload_router, prefix="/api/v1")
app.include_router(approval_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": settings.APP_VERSION}
