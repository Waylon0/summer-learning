"""
=============================================================================
app/api/v1/budget.py — 部门预算 API（增强版）
=============================================================================
BudgetNotFoundError → 全局异常处理器 → 自动返回 404

权限：需登录。
  - employee/manager: 仅可查看本部门预算
  - admin/finance   : 可查看全部部门预算
=============================================================================
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.core.deps import get_current_user
from app.services.reimbursement_svc import BudgetService
from app.schemas.reimbursement import BudgetResponse
from app.models.user import User

router = APIRouter(prefix="/budget", tags=["budget"])


@router.get("/{department}", response_model=BudgetResponse)
async def get_department_budget(
    department: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询单个部门预算（员工/经理仅限本部门）"""
    if user.role not in ("admin", "finance") and department != user.department:
        raise HTTPException(status_code=403, detail=f"无权查看「{department}」的预算，您仅可查看本部门（{user.department}）")
    svc = BudgetService(db)
    bud = await svc.get_by_department(department)  # 抛 BudgetNotFoundError → 404
    logger.info(f"预算查询: {department} by {user.username} 剩余={float(bud.annual_budget - bud.used_amount)}")
    return BudgetResponse(
        id=bud.id,
        department=bud.department,
        annual_budget=float(bud.annual_budget),
        used_amount=float(bud.used_amount),
        remaining=float(bud.annual_budget - bud.used_amount),
        fiscal_year=bud.fiscal_year,
        usage_rate=float(bud.used_amount / bud.annual_budget * 100) if bud.annual_budget > 0 else 0,
    )


@router.get("", response_model=list[BudgetResponse])
async def list_all_budgets(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出部门预算（员工/经理仅返回本部门，管理员/财务返回全部）"""
    svc = BudgetService(db)
    buds = await svc.list_all()
    if user.role not in ("admin", "finance"):
        buds = [b for b in buds if b.department == user.department]
    logger.info(f"预算列表查询: {len(buds)} 个部门 by {user.username}({user.role})")
    return [
        BudgetResponse(
            id=b.id,
            department=b.department,
            annual_budget=float(b.annual_budget),
            used_amount=float(b.used_amount),
            remaining=float(b.annual_budget - b.used_amount),
            fiscal_year=b.fiscal_year,
            usage_rate=float(b.used_amount / b.annual_budget * 100) if b.annual_budget > 0 else 0,
        )
        for b in buds
    ]
