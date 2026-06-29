from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.reimbursement_svc import BudgetService
from app.schemas.reimbursement import BudgetResponse

router = APIRouter(prefix="/budget", tags=["budget"])


@router.get("/{department}", response_model=BudgetResponse)
async def get_department_budget(department: str, db: AsyncSession = Depends(get_db)):
    svc = BudgetService(db)
    bud = await svc.get_by_department(department)
    if not bud:
        raise HTTPException(status_code=404, detail=f"部门 '{department}' 的预算信息不存在")
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
    svc = BudgetService(db)
    buds = await svc.list_all()
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
