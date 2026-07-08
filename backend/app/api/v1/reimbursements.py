"""
=============================================================================
app/api/v1/reimbursements.py — 报销单 CRUD API（用户隔离）
=============================================================================
- employee: 只能创建/查看本人的报销单
- manager: 可查看本部门全部报销单
- admin/finance: 可查看全部报销单
=============================================================================
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.core.deps import get_current_user, get_optional_user
from app.services.reimbursement_svc import ReimbursementService
from app.schemas.reimbursement import ReimbursementCreate, ReimbursementResponse
from app.models.user import User

router = APIRouter(prefix="/reimbursements", tags=["reimbursements"])


@router.post("", response_model=ReimbursementResponse)
async def create_reimbursement(
    data: ReimbursementCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建报销单 — 自动绑定当前登录用户"""
    svc = ReimbursementService(db)
    logger.info(f"创建报销: user={user.name} dept={data.department} type={data.expense_type}")
    reimb = await svc.create(data, data.invoices)
    await db.refresh(reimb, ["invoices", "approvals"])
    return _to_response(reimb)


@router.get("/{reimb_id}", response_model=ReimbursementResponse)
async def get_reimbursement(
    reimb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询单个报销单 — 普通员工只能查自己的"""
    svc = ReimbursementService(db)
    reimb = await svc.get_by_id(reimb_id)
    # 权限检查
    if user.role == "employee" and reimb.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权查看他人的报销单")
    if user.role == "manager" and reimb.department != user.department:
        raise HTTPException(status_code=403, detail=f"无权查看{reimb.department}的报销单")
    return _to_response(reimb)


@router.get("", response_model=list[ReimbursementResponse])
async def list_reimbursements(
    user_id: str = None,
    status: str = None,
    department: str = None,
    expense_type: str = None,
    keyword: str = None,
    amount_min: float = None,
    amount_max: float = None,
    amount_exact: float = None,
    date_from: str = None,
    date_to: str = None,
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """多维度查询报销单列表（权限隔离）"""
    svc = ReimbursementService(db)
    # 权限范围
    if user.role == "employee":
        user_id = user.id  # 强制只看自己
    elif user.role == "manager":
        if department and department != user.department:
            raise HTTPException(status_code=403, detail=f"只能查看{user.department}的报销单")
        department = user.department  # 只看本部门

    reimbs, total = await svc.search(
        user_id=user_id, status=status, department=department,
        expense_type=expense_type, keyword=keyword,
        amount_min=amount_min, amount_max=amount_max, amount_exact=amount_exact,
        date_from=date_from, date_to=date_to,
        sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset,
    )
    return [_to_response(r) for r in reimbs]


def _to_response(reimb) -> ReimbursementResponse:
    return ReimbursementResponse(
        id=reimb.id, user_id=reimb.user_id, user_name=reimb.user_name,
        department=reimb.department, expense_type=reimb.expense_type,
        total_amount=float(reimb.total_amount), description=reimb.description,
        invoice_count=reimb.invoice_count,
        need_special_approval=reimb.need_special_approval,
        budget_remaining_after=float(reimb.budget_remaining_after) if reimb.budget_remaining_after else None,
        status=reimb.status,
        created_at=reimb.created_at.isoformat() if reimb.created_at else None,
        updated_at=reimb.updated_at.isoformat() if reimb.updated_at else None,
        invoices=[i.to_dict() for i in (reimb.invoices or [])],
        approvals=[a.to_dict() for a in (reimb.approvals or [])],
    )
