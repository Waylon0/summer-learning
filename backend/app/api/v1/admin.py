"""
=============================================================================
app/api/v1/admin.py — 超级管理员用户管理 API
=============================================================================
仅 admin 角色可访问：列出用户、晋升角色、禁用用户。
=============================================================================
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.user import User

router = APIRouter(prefix="/admin/users", tags=["admin"])


class RoleUpdateRequest(BaseModel):
    """变更用户角色请求体"""
    role: str = Field(..., description="目标角色: employee / manager / finance / admin")


@router.get("")
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    """列出所有用户（仅超管）"""
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [u.to_dict() for u in users]


@router.put("/{user_id}/role")
async def update_user_role(
    user_id: str,
    data: RoleUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    """
    变更用户角色（仅超管）。

    role 可选: employee / manager / finance / admin（支持升级与降级）。
    返回更新后的用户信息（UserInfo）。
    """
    valid_roles = {"employee", "manager", "finance", "admin"}
    if data.role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"无效目标角色: {data.role}，可选: {sorted(valid_roles)}")

    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    old_role = user.role
    user.role = data.role
    await db.commit()
    await db.refresh(user)

    logger.info(f"用户角色变更: {user.username} {old_role}→{data.role} by {admin.username}")
    return user.to_dict()


@router.put("/{user_id}/deactivate")
async def deactivate_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    """禁用/启用用户（仅超管）"""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="不能禁用自己")

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user.is_active = not user.is_active
    await db.commit()

    status = "禁用" if not user.is_active else "启用"
    logger.info(f"用户状态变更: {user.username} → {status} by {admin.username}")
    return {"user_id": user_id, "username": user.username, "is_active": user.is_active, "message": f"已{status}"}
