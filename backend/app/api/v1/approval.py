"""
=============================================================================
app/api/v1/approval.py — 审批操作 API（增强版）
=============================================================================
异常由全局处理器统一捕获，路由层只关注业务调用。
=============================================================================
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.services.reimbursement_svc import ApprovalService
from app.schemas.reimbursement import ApprovalAction

router = APIRouter(prefix="/approval", tags=["approval"])


@router.post("")
async def submit_approval(
    action: ApprovalAction,
    db: AsyncSession = Depends(get_db),
):
    """
    提交审批操作。

    有效动作: approve(通过) / reject(驳回) / return(退回)

    异常处理:
      - 报销单不存在 → ReimbursementNotFoundError → 404
      - 无效动作       → BusinessException      → 400
    """
    logger.info(f"审批请求: reimb={action.reimbursement_id} action={action.action}")
    svc = ApprovalService(db)
    record = await svc.record(
        action.reimbursement_id,
        action.approver,
        action.action,
        action.comment,
    )
    return record.to_dict()
