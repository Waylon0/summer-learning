"""
=============================================================================
app/api/v1/auth.py — 认证 API (register / login / me)
=============================================================================
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.core.deps import get_current_user
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, UserResponse
from app.services.auth_svc import AuthService
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """用户注册"""
    svc = AuthService(db)
    return await svc.register(
        username=data.username,
        password=data.password,
        name=data.name,
        department=data.department,
        email=data.email,
        role=data.role,
    )


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    svc = AuthService(db)
    return await svc.login(data.username, data.password)


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """获取当前登录用户信息"""
    return UserResponse(
        id=user.id,
        username=user.username,
        name=user.name,
        email=user.email,
        department=user.department,
        role=user.role,
        is_active=user.is_active,
        created_at=user.created_at.isoformat() if user.created_at else None,
    )
