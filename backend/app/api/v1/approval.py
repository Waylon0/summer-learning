"""
=============================================================================
app/api/v1/approval.py — 审批操作 API（部门经理权限守卫）
=============================================================================
审批人必须是 department_manager / admin / finance 角色。
审批人只能审批本部门的报销单（admin/finance 可跨部门）。
=============================================================================
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
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
    提交审批操作（仅部门经理及以上角色可操作）。

    权限规则:
      - employee 角色: 403 拒绝
      - manager 角色: 只能审批本部门报销单
      - admin/finance 角色: 可审批所有报销单
    """
    logger.info(f"审批请求: user={approver.username}({approver.role}) reimb={action.reimbursement_id} action={action.action}")

    # 非 admin/finance 的 manager 只能审批本部门报销单
    if approver.role not in ("admin", "finance"):
        reimb = await db.get(Reimbursement, action.reimbursement_id)
        if not reimb:
            raise HTTPException(status_code=404, detail="报销单不存在")
        if reimb.department != approver.department:
            raise HTTPException(
                status_code=403,
                detail=f"您只能审批{approver.department}的报销单，该报销单属于{reimb.department}",
            )
        # employee 角色已在 require_department_manager 中拒绝

    svc = ApprovalService(db)
    record = await svc.record(
        action.reimbursement_id,
        approver.name,  # 使用 JWT 中的真实姓名
        action.action,
        action.comment,
    )
    return record.to_dict()
