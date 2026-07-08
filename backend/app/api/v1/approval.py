"""
=============================================================================
app/api/v1/approval.py — 审批操作 API（部门经理/超管权限）
=============================================================================
多经理制：同一部门可有多位经理，任意一位审批通过即可。
管理员可跨部门审批。
=============================================================================
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.core.deps import get_current_user, require_department_manager
from app.services.reimbursement_svc import ApprovalService
from app.schemas.reimbursement import ApprovalAction
from app.models.user import User
from app.models.reimbursement import Reimbursement

router = APIRouter(prefix="/approval", tags=["approval"])


@router.post("")
async def submit_approval(
    action: ApprovalAction,
    db: AsyncSession = Depends(get_db),
    approver: User = Depends(require_department_manager()),
):
    """
    提交审批操作（部门经理或超管可操作）。

    多经理制:
      - 同一部门可有多位经理，任意一位审批通过即可
      - 管理员可跨部门审批
      - 员工 403 拒绝
    """
    logger.info(f"审批请求: user={approver.username}({approver.role}) reimb={action.reimbursement_id} action={action.action}")

    # 管理员可跨部门，经理只能审批本部门
    if approver.role != "admin":
        reimb = await db.get(Reimbursement, action.reimbursement_id)
        if not reimb:
            raise HTTPException(status_code=404, detail="报销单不存在")
        if reimb.department != approver.department:
            raise HTTPException(
                status_code=403,
                detail=f"您只能审批{approver.department}的报销单，该报销单属于{reimb.department}",
            )

    svc = ApprovalService(db)
    record = await svc.record(
        action.reimbursement_id,
        approver.name,
        action.action,
        action.comment,
    )
    return record.to_dict()
