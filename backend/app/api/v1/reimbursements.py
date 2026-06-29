from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.reimbursement_svc import ReimbursementService
from app.schemas.reimbursement import ReimbursementCreate, ReimbursementResponse

router = APIRouter(prefix="/reimbursements", tags=["reimbursements"])


@router.post("", response_model=ReimbursementResponse)
async def create_reimbursement(data: ReimbursementCreate, db: AsyncSession = Depends(get_db)):
    svc = ReimbursementService(db)
    reimb = await svc.create(data, data.invoices)
    await db.refresh(reimb, ["invoices", "approvals"])
    return _to_response(reimb)


@router.get("/{reimb_id}", response_model=ReimbursementResponse)
async def get_reimbursement(reimb_id: str, db: AsyncSession = Depends(get_db)):
    svc = ReimbursementService(db)
    reimb = await svc.get_by_id(reimb_id)
    if not reimb:
        raise HTTPException(status_code=404, detail="报销单不存在")
    return _to_response(reimb)


@router.get("", response_model=list[ReimbursementResponse])
async def list_reimbursements(
    user_id: str = None,
    status: str = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    svc = ReimbursementService(db)
    if user_id:
        reimbs = await svc.list_by_user(user_id, limit)
    else:
        reimbs = await svc.list_by_status(status, limit=limit)
    return [_to_response(r) for r in reimbs]


def _to_response(reimb) -> ReimbursementResponse:
    return ReimbursementResponse(
        id=reimb.id,
        user_id=reimb.user_id,
        user_name=reimb.user_name,
        department=reimb.department,
        expense_type=reimb.expense_type,
        total_amount=float(reimb.total_amount),
        description=reimb.description,
        invoice_count=reimb.invoice_count,
        need_special_approval=reimb.need_special_approval,
        budget_remaining_after=float(reimb.budget_remaining_after) if reimb.budget_remaining_after else None,
        status=reimb.status,
        created_at=reimb.created_at.isoformat() if reimb.created_at else None,
        updated_at=reimb.updated_at.isoformat() if reimb.updated_at else None,
        invoices=[i.to_dict() for i in (reimb.invoices or [])],
        approvals=[a.to_dict() for a in (reimb.approvals or [])],
    )
