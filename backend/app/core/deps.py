"""
=============================================================================
app/core/deps.py — FastAPI 认证依赖
=============================================================================
提供 get_current_user, require_role, get_optional_user 等依赖注入。
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 JWT token 提取当前登录用户"""
    if not credentials:
        raise HTTPException(status_code=401, detail="请先登录")

    payload = decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="无效的认证令牌")

    user = await db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """可选认证：已登录返回用户，未登录返回 None"""
    if not credentials:
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload:
        return None
    return await db.get(User, payload.get("sub"))


def require_role(*roles: str):
    """角色守卫：只允许指定角色访问"""
    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"权限不足，需要角色: {roles}",
            )
        return user
    return dependency


def require_department_manager():
    """
    部门经理守卫：
    - manager 角色可以通过
    - admin/finance 角色也可以通过（全局权限）
    - employee 角色拒绝
    """
    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role == "employee":
            raise HTTPException(
                status_code=403,
                detail="只有部门经理及以上角色可以执行审批操作",
            )
        return user
    return dependency
