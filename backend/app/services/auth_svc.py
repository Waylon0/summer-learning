"""
=============================================================================
app/services/auth_svc.py — 用户认证服务
=============================================================================
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.user import User
from app.core.security import hash_password, verify_password, create_access_token
from app.core.exceptions import BusinessException, NotFoundException


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(
        self, username: str, password: str, name: str,
        department: str, email: str = None, role: str = "employee",
    ) -> dict:
        """注册新用户"""
        existing = await self.db.scalar(
            select(User).where(User.username == username)
        )
        if existing:
            raise BusinessException(
                message=f"用户名 '{username}' 已被注册",
                error_code="USERNAME_EXISTS",
            )

        valid_roles = {"employee", "manager", "admin", "finance"}
        if role not in valid_roles:
            raise BusinessException(
                message=f"无效角色: {role}，允许值: {valid_roles}",
                error_code="INVALID_ROLE",
            )

        user = User(
            username=username,
            password_hash=hash_password(password),
            name=name,
            email=email,
            department=department,
            role=role,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        token = create_access_token(user.id, user.username, user.department, user.role)
        logger.info(f"User registered: {username} ({user.role}) dept={department}")
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user.to_dict(),
        }

    async def login(self, username: str, password: str) -> dict:
        """用户登录"""
        user = await self.db.scalar(
            select(User).where(User.username == username)
        )
        if not user:
            raise BusinessException(
                message="用户名或密码错误",
                error_code="AUTH_FAILED",
            )
        if not user.is_active:
            raise BusinessException(
                message="账户已被禁用，请联系管理员",
                error_code="ACCOUNT_DISABLED",
            )
        if not verify_password(password, user.password_hash):
            raise BusinessException(
                message="用户名或密码错误",
                error_code="AUTH_FAILED",
            )

        token = create_access_token(user.id, user.username, user.department, user.role)
        logger.info(f"User login: {username} ({user.role})")
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": user.to_dict(),
        }

    async def get_user_by_id(self, user_id: str) -> User:
        user = await self.db.get(User, user_id)
        if not user:
            raise NotFoundException(resource="用户", identifier=user_id)
        return user
