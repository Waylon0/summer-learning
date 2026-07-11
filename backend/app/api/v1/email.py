"""
=============================================================================
app/api/v1/email.py — 邮件发送 API
=============================================================================
- POST /email/send            通用发信（可选附带某报销单 PDF）
- POST /email/notify/{reimb_id} 手动触发审批通知（重发/测试用）

权限：仅 manager / finance / admin 可主动发信（员工不可）。
说明：SMTP 账号只是固定的【发件人】，收件人可为任意邮箱；
      发送失败仅返回 sent=false，不抛异常。
=============================================================================
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User

router = APIRouter(prefix="/email", tags=["email"])


class EmailSendRequest(BaseModel):
    to: str = Field(..., description="收件人邮箱")
    subject: str = Field(..., description="邮件主题")
    body: str = Field(..., description="邮件正文（支持 HTML）")
    reimb_id: str = Field("", description="可选：附带该报销单的 PDF")


async def _reimb_pdf_bytes(db: AsyncSession, reimb_id: str, user: User):
    """加载报销单（带权限校验）并生成 PDF 字节，用于邮件附件。"""
    from app.services.expense_sheet_svc import ExpenseSheetService
    from app.services.notification_svc import _pdf_bytes_for
    from app.core.exceptions import ReimbursementNotFoundError
    try:
        reimb = await ExpenseSheetService(db).get(reimb_id)
    except ReimbursementNotFoundError:
        raise HTTPException(status_code=404, detail="报销单不存在")
    if user.role == "employee" and reimb.user_id != user.id:
        raise HTTPException(status_code=403, detail="只能附带本人的报销单")
    if user.role == "manager" and reimb.department != user.department:
        raise HTTPException(status_code=403, detail=f"只能附带本部门（{user.department}）的报销单")
    return await _pdf_bytes_for(reimb)


@router.post("/send")
async def send_email_api(
    req: EmailSendRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """发送一封邮件（可选附带某报销单 PDF）。仅 manager/finance/admin 可用。"""
    if user.role == "employee":
        raise HTTPException(status_code=403, detail="员工无发信权限")
    from app.services.email_svc import send_email

    pdf_bytes, pdf_name = (None, None)
    if req.reimb_id:
        pdf_bytes, pdf_name = await _reimb_pdf_bytes(db, req.reimb_id, user)

    ok = await send_email(
        req.to, req.subject, req.body,
        attachment_bytes=pdf_bytes, attachment_name=pdf_name,
    )
    logger.info(f"手动发信: by={user.username} to={req.to} reimb={req.reimb_id or '-'} sent={ok}")
    if not ok:
        # 未配置 SMTP 或发送失败：返回 200 但标注 sent=false，附排查提示
        return {"sent": False, "to": req.to,
                "message": "邮件发送失败：请检查 SMTP 配置（SMTP_HOST/USER/PASSWORD）与收件邮箱。"}
    return {"sent": True, "to": req.to, "message": "邮件已发送。"}


@router.post("/notify/{reimb_id}")
async def notify_api(
    reimb_id: str,
    stage: str = "manager",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """手动触发审批通知（stage=manager 一审 / finance 二审）。用于重发或测试。"""
    if user.role == "employee":
        raise HTTPException(status_code=403, detail="员工无权触发审批通知")
    if stage not in ("manager", "finance"):
        raise HTTPException(status_code=400, detail="stage 只能是 manager 或 finance")
    from app.services.notification_svc import send_reimbursement_notification
    result = await send_reimbursement_notification(reimb_id, stage)
    return {
        "reimb_id": reimb_id, "stage": stage,
        "sent_count": result.get("sent", 0),
        "recipients": result.get("recipients", []),
        "message": (
            f"已向 {result.get('sent', 0)} 位收件人发送通知"
            if result.get("sent") else
            "未发送成功（可能无匹配收件人、其未填邮箱、或 SMTP 未配置）"
        ),
    }
