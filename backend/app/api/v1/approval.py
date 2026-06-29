from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.reimbursement_svc import ApprovalService
from app.schemas.reimbursement import ApprovalAction

router = APIRouter(prefix="/approval", tags=["approval"])


@router.post("")
async def submit_approval(action: ApprovalAction, db: AsyncSession = Depends(get_db)):
    svc = ApprovalService(db)
    try:
        record = await svc.record(
            action.reimbursement_id,
            action.approver,
            action.action,
            action.comment,
        )
        return record.to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
