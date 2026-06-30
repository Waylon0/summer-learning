"""
=============================================================================
app/api/v1/approval.py — 审批操作 API
=============================================================================
POST /api/v1/approval — 提交审批操作（通过/驳回/退回）
=============================================================================
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.reimbursement_svc import ApprovalService
from app.schemas.reimbursement import ApprovalAction

router = APIRouter(prefix="/approval", tags=["approval"])


@router.post("")
async def submit_approval(
    action: ApprovalAction,                                # 前端传来的审批操作
    db: AsyncSession = Depends(get_db),
):
    """
    审批人提交审批操作。

    请求示例：
      {
        "reimbursement_id": "abc-123",
        "approver": "张经理",
        "action": "approve",
        "comment": "费用合理，同意报销"
      }

    action 可选值：
      - approve : 通过
      - reject  : 驳回
      - return  : 退回修改
    """
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
        # 报销单不存在时返回 404
        raise HTTPException(status_code=404, detail=str(e))
