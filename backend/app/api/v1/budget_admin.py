"""
=============================================================================
app/api/v1/budget_admin.py — 部门预算【管理】API（预算管理模块 · 阶段一）
=============================================================================
在既有只读预算 API（app/api/v1/budget.py）之上，新增企业运维所需的写操作：
  POST   /budget                         新建部门预算
  PATCH  /budget/{department}            调整年度额度（增/减/绝对改写）
  POST   /budget/{department}/correction 人工冲正 used_amount（手工修账）
  POST   /budget/transfer                部门间额度调拨（一增一减，同事务）
  GET    /budget/{department}/adjustments 预算变更流水（审计）
  GET    /budget/{department}/consumption 预算消耗明细（占用该部门预算的报销单）

权限：写操作 admin + finance；审计/消耗 admin/finance（消耗允许本部门经理下钻）。
业务异常（BusinessException/BudgetNotFoundError）由全局异常处理器统一转 HTTP。
=============================================================================
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.core.deps import get_current_user, require_role
from app.models.user import User
from app.services.budget_admin_svc import BudgetAdminService
from app.schemas.reimbursement import (
    BudgetResponse, BudgetAdjustmentResponse,
    BudgetCreateRequest, BudgetAdjustRequest,
    BudgetCorrectionRequest, BudgetTransferRequest,
)

router = APIRouter(prefix="/budget", tags=["budget-admin"])

# 预算写操作允许的角色（已敲定：admin + finance）
_budget_writer = require_role("admin", "finance")


def _budget_resp(b) -> BudgetResponse:
    d = b.to_dict()
    return BudgetResponse(**{k: d[k] for k in (
        "id", "department", "annual_budget", "used_amount", "remaining",
        "fiscal_year", "usage_rate", "status", "note", "updated_at",
    )})


# =============================================================================
# 新建部门预算
# =============================================================================
@router.post("", status_code=201)
async def create_budget(
    data: BudgetCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_budget_writer),
):
    """新建部门预算（admin/finance）。部门已存在则返回 400（请改用调整接口）。"""
    svc = BudgetAdminService(db)
    budget, audit = await svc.create_budget(
        department=data.department, annual_budget=data.annual_budget,
        fiscal_year=data.fiscal_year, operator=user.name, operator_role=user.role,
        note=data.note,
    )
    logger.info(f"[API] 新建预算 {data.department} by {user.username}")
    return {"budget": _budget_resp(budget), "adjustment": BudgetAdjustmentResponse(**audit.to_dict())}


# =============================================================================
# 调整年度额度
# =============================================================================
@router.patch("/{department}")
async def adjust_annual(
    department: str,
    data: BudgetAdjustRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_budget_writer),
):
    """调整部门年度额度（admin/finance）。delta 增量 或 new_annual_budget 绝对改写二选一。"""
    svc = BudgetAdminService(db)
    budget, audit = await svc.adjust_annual(
        department=department, operator=user.name, operator_role=user.role,
        reason=data.reason, delta=data.delta,
        new_annual_budget=data.new_annual_budget, force=data.force,
    )
    logger.info(f"[API] 调整预算 {department} by {user.username}")
    return {"budget": _budget_resp(budget), "adjustment": BudgetAdjustmentResponse(**audit.to_dict())}


# =============================================================================
# 人工冲正 used_amount
# =============================================================================
@router.post("/{department}/correction")
async def correct_used(
    department: str,
    data: BudgetCorrectionRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_budget_writer),
):
    """人工冲正部门已用额 used_amount（admin/finance），用于手工修账。冲正后不为负（夹 0）。"""
    svc = BudgetAdminService(db)
    budget, audit = await svc.correct_used(
        department=department, delta_used=data.delta_used,
        operator=user.name, operator_role=user.role, reason=data.reason,
    )
    logger.info(f"[API] 冲正预算 {department} Δ{data.delta_used} by {user.username}")
    return {"budget": _budget_resp(budget), "adjustment": BudgetAdjustmentResponse(**audit.to_dict())}


# =============================================================================
# 部门间调拨
# =============================================================================
@router.post("/transfer")
async def transfer_budget(
    data: BudgetTransferRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_budget_writer),
):
    """部门间额度调拨（admin/finance）：from_dept 转出 amount 到 to_dept，一增一减同事务。"""
    svc = BudgetAdminService(db)
    b_from, b_to, audits = await svc.transfer(
        from_dept=data.from_dept, to_dept=data.to_dept, amount=data.amount,
        operator=user.name, operator_role=user.role, reason=data.reason, force=data.force,
    )
    logger.info(f"[API] 预算调拨 {data.from_dept}→{data.to_dept} ¥{data.amount} by {user.username}")
    return {
        "from_budget": _budget_resp(b_from),
        "to_budget": _budget_resp(b_to),
        "adjustments": [BudgetAdjustmentResponse(**a.to_dict()) for a in audits],
    }


# =============================================================================
# 预算变更流水（审计）
# =============================================================================
@router.get("/{department}/adjustments", response_model=list[BudgetAdjustmentResponse])
async def list_adjustments(
    department: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("admin", "finance")),
):
    """查看某部门预算变更流水（admin/finance）。"""
    svc = BudgetAdminService(db)
    rows = await svc.list_adjustments(department, limit=limit)
    return [BudgetAdjustmentResponse(**r.to_dict()) for r in rows]


# =============================================================================
# 预算消耗明细（占用该部门预算的报销单）
# =============================================================================
@router.get("/{department}/consumption")
async def list_consumption(
    department: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """预算消耗下钻：列出占用该部门预算（待审批/已通过/已付款）的报销单及占用总额。

    权限：admin/finance 可查任意部门；manager 仅可查本部门；employee 拒绝。
    """
    from fastapi import HTTPException
    if user.role == "employee":
        raise HTTPException(status_code=403, detail="无权查看预算消耗明细")
    if user.role == "manager" and department != user.department:
        raise HTTPException(status_code=403, detail=f"仅可查看本部门（{user.department}）的预算消耗")

    svc = BudgetAdminService(db)
    rows, total = await svc.list_consumption(department, limit=limit)
    return {
        "department": department,
        "committed_total": total,
        "count": len(rows),
        "reimbursements": [
            {
                "id": r.id, "user_name": r.user_name, "expense_type": r.expense_type,
                "title": r.title or "", "total_amount": float(r.total_amount or 0),
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
