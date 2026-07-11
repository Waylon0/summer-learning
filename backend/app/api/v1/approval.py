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
from app.schemas.reimbursement import ApprovalAction, PaymentRequest
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

    # 管理员/财务可跨部门审批，部门经理只能审批本部门
    if approver.role == "manager":
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
        approver_role=approver.role,
    )
    # budget transition already applied by ApprovalService.record internally;
    # for approve, delta=0 (budget stays reserved from submit).
    # reject/return would release budget (delta<0).
    # No additional apply_status_transition_budget call needed here.

    # 审批完成后重新生成 PDF（反映最新审批记录），失败不阻断
    pdf_url = ""
    try:
        from app.services.pdf_svc import generate_and_store_reimbursement_pdf
        from app.services.expense_sheet_svc import ExpenseSheetService
        reimb_fresh = await ExpenseSheetService(db).get(action.reimbursement_id)
        info = await generate_and_store_reimbursement_pdf(reimb_fresh)
        pdf_url = info.get("download_url", "")
    except Exception as e:
        logger.warning(f"审批后重新生成 PDF 失败（不阻断）: {e}")
    result = record.to_dict()
    if pdf_url:
        result["pdf_download_url"] = pdf_url

    # 一审（部门经理）通过 → 报销单仍为 pending → 进入二审，自动邮件通知财务
    if action.action == "approve":
        reimb = await db.get(Reimbursement, action.reimbursement_id)
        if reimb and reimb.status == "pending":
            try:
                from app.services.notification_svc import dispatch_reimbursement_notification
                dispatch_reimbursement_notification(action.reimbursement_id, "finance")
            except Exception as e:
                logger.warning(f"一审通过后通知财务失败（不阻断）: {e}")
    return result


@router.post("/pay")
async def pay_reimbursement(
    req: PaymentRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """出纳付款：已通过(approved) → 已付款(paid)。仅财务/出纳或管理员可操作。"""
    from app.core.exceptions import BusinessException
    if user.role not in ("finance", "admin"):
        raise HTTPException(status_code=403, detail="只有财务/出纳可执行付款操作")
    svc = ApprovalService(db)
    try:
        record = await svc.mark_paid(
            req.reimbursement_id, user.name,
            operator_role=user.role, comment=req.comment,
        )
    except BusinessException as e:
        raise HTTPException(status_code=400, detail=e.message)
    # 付款后重新生成 PDF（反映最终状态与完整审批链），失败不阻断
    pdf_url = ""
    try:
        from app.services.pdf_svc import generate_and_store_reimbursement_pdf
        from app.services.expense_sheet_svc import ExpenseSheetService
        reimb_fresh = await ExpenseSheetService(db).get(req.reimbursement_id)
        info = await generate_and_store_reimbursement_pdf(reimb_fresh)
        pdf_url = info.get("download_url", "")
    except Exception as e:
        logger.warning(f"付款后重新生成 PDF 失败（不阻断）: {e}")
    result = record.to_dict()
    if pdf_url:
        result["pdf_download_url"] = pdf_url
    logger.info(f"付款请求: user={user.username} reimb={req.reimbursement_id}")
    return result
