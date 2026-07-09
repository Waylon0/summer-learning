"""
=============================================================================
app/api/v1/reimbursements.py — 报销单 CRUD API（用户隔离 + 撤销）
=============================================================================
- employee: 只能创建/查看本人的报销单，可撤销 pending 状态的自己的单子
- manager: 可查看本部门全部报销单、审批本部门报销
- admin: 全局权限，可查看全部报销单
=============================================================================
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db, engine
from app.core.deps import get_current_user
from app.services.reimbursement_svc import ReimbursementService
from app.services.pdf_svc import generate_and_store_reimbursement_pdf
from app.schemas.reimbursement import (
    ReimbursementCreate, ReimbursementResponse, ReimbursementPdfResponse,
)
from app.models.user import User
from app.core.exceptions import InternalErrorException

router = APIRouter(prefix="/reimbursements", tags=["reimbursements"])


@router.post("", response_model=ReimbursementResponse)
async def create_reimbursement(
    data: ReimbursementCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建报销单 — 自动绑定当前登录用户"""
    # 强制覆盖为 JWT 用户信息（防止伪造）
    data.user_id = user.id
    data.user_name = user.name
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
    """查询单个报销单 — 权限隔离"""
    svc = ReimbursementService(db)
    reimb = await svc.get_by_id(reimb_id)
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
    if user.role == "employee":
        user_id = user.id
    elif user.role == "manager":
        if department and department != user.department:
            raise HTTPException(status_code=403, detail=f"只能查看{user.department}的报销单")
        department = user.department

    reimbs, total = await svc.search(
        user_id=user_id, status=status, department=department,
        expense_type=expense_type, keyword=keyword,
        amount_min=amount_min, amount_max=amount_max, amount_exact=amount_exact,
        date_from=date_from, date_to=date_to,
        sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset,
    )
    return [_to_response(r) for r in reimbs]


@router.post("/{reimb_id}/cancel")
async def cancel_reimbursement(
    reimb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    撤销报销单 — 仅 pending 状态且为本人提交的可撤销。

    权限:
      - employee: 只能撤销自己的 pending 报销单
      - manager/admin: 可撤销本部门/全部 pending 报销单
    """
    svc = ReimbursementService(db)
    reimb = await svc.get_by_id(reimb_id)

    # 权限检查
    if user.role == "employee" and reimb.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能撤销自己的报销单")
    if user.role == "manager" and reimb.department != user.department:
        raise HTTPException(status_code=403, detail=f"无权撤销{reimb.department}的报销单")

    # 状态检查
    if reimb.status != "pending":
        readable_status = {"approved": "已通过", "rejected": "已驳回", "returned": "已退回", "paid": "已付款", "cancelled": "已撤销"}
        cn = readable_status.get(reimb.status, reimb.status)
        raise HTTPException(status_code=400, detail=f"报销单状态为「{cn}」，只有「待审批」状态才能撤销")

    # 执行撤销
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE reimbursements SET status = 'cancelled' WHERE id = :rid"), {"rid": reimb_id})
        await conn.execute(text("UPDATE approval_records SET action = 'cancelled', comment = '申请人主动撤销' WHERE reimbursement_id = :rid"), {"rid": reimb_id})

    logger.info(f"报销单撤销: {reimb_id} by {user.username}")
    return {"reimb_id": reimb_id, "status": "cancelled", "message": "报销单已撤销"}


@router.post("/{reimb_id}/pdf", response_model=ReimbursementPdfResponse)
async def generate_reimbursement_pdf_endpoint(
    reimb_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    生成报销单结构化 PDF 并返回下载地址。

    权限:
      - employee: 仅可为本人报销单生成
      - manager : 仅可为本部门报销单生成
      - admin/finance: 全部
    """
    svc = ReimbursementService(db)
    reimb = await svc.get_by_id(reimb_id)  # 不存在 → 404

    if user.role == "employee" and reimb.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能为本人的报销单生成 PDF")
    if user.role == "manager" and reimb.department != user.department:
        raise HTTPException(status_code=403, detail=f"无权为{reimb.department}的报销单生成 PDF")

    try:
        info = await generate_and_store_reimbursement_pdf(reimb)
    except Exception as e:
        logger.error(f"报销单 PDF 生成失败: {e}")
        raise InternalErrorException(message="报销单 PDF 生成失败", detail={"error": str(e)})

    logger.info(f"报销单 PDF 生成: {reimb_id} by {user.username} → {info['object_name']}")
    return ReimbursementPdfResponse(**info)


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
