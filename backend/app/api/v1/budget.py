"""
=============================================================================
app/api/v1/budget.py — 部门预算 API（增强版）
=============================================================================
BudgetNotFoundError → 全局异常处理器 → 自动返回 404
=============================================================================
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.services.reimbursement_svc import BudgetService
from app.schemas.reimbursement import BudgetResponse

router = APIRouter(prefix="/budget", tags=["budget"])


@router.get("/{department}", response_model=BudgetResponse)
async def get_department_budget(
    department: str,
    db: AsyncSession = Depends(get_db),
):
    """查询单个部门预算"""
    svc = BudgetService(db)
    bud = await svc.get_by_department(department)  # 抛 BudgetNotFoundError → 404
    logger.info(f"预算查询: {department} 剩余={float(bud.annual_budget - bud.used_amount)}")
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
async def list_all_budgets(db: AsyncSession = Depends(get_db)):
    """列出所有部门预算"""
    svc = BudgetService(db)
    buds = await svc.list_all()
    logger.info(f"预算列表查询: {len(buds)} 个部门")
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
