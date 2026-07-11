"""
=============================================================================
app/services/notification_svc.py — 报销审批邮件通知
=============================================================================
关于 SMTP 与"发给不同用户"的说明（核心思路）:
  - SMTP 账号（SMTP_USER + 密码）只是【认证的发件人】，即"由谁来寄信"（From 固定为公司账号）。
  - 收件人（To）可以是【任意】邮箱地址。一个公司 SMTP 账号能给成千上万个不同用户发信，
    就像一个邮局用同一个寄件人地址，把信寄往千家万户。
  - 因此"发给不同用户"= 从 users 表里查出目标用户的 email，作为 To 即可；
    真正的前提是：每个需要收信的用户在系统里【配置了 email】。

通知触发（两阶段审批）:
  1. 申请人成功提交报销单  → 通知【申请人所在部门的部门经理】进行一审（附报销单 PDF）。
  2. 部门经理一审通过后    → 通知【财务】进行二审（附报销单 PDF）。

设计原则:
  - 全部【尽力而为】：找不到收件人 / SMTP 未配置 / 发送失败，都只记日志，
    绝不抛异常打断报销提交或审批主流程。
  - 通过 dispatch_* 以后台任务（fire-and-forget）方式发送，不阻塞 Agent/接口响应。
=============================================================================
"""
from __future__ import annotations

import asyncio

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.user import User


# 阶段 → (目标角色, 中文阶段名)
_STAGE_TARGET = {
    "manager": ("manager", "一审（部门经理）"),
    "finance": ("finance", "二审（财务）"),
}


async def resolve_role_emails(
    db: AsyncSession, role: str, department: str | None = None
) -> list[dict]:
    """查出某角色（可限定部门）下所有【启用且填写了邮箱】的用户。

    返回 [{name, email, department}]。department=None 表示不限部门（如财务跨部门）。
    """
    conds = [User.role == role, User.is_active == True]  # noqa: E712
    if department:
        conds.append(User.department == department)
    rows = (await db.execute(select(User).where(*conds))).scalars().all()
    result = []
    for u in rows:
        email = (u.email or "").strip()
        if email:
            result.append({"name": u.name, "email": email, "department": u.department})
    return result


def _build_email(reimb, stage_cn: str) -> tuple[str, str]:
    """构造审批提醒邮件的主题与 HTML 正文。"""
    total = float(reimb.total_amount or 0)
    subject = f"【报销审批提醒·{stage_cn}】{reimb.user_name} 提交的报销单待审批 - ¥{total:,.2f}"
    body = f"""
    <div style="font-family:微软雅黑,Arial,sans-serif;font-size:14px;color:#333;">
      <h2 style="color:#c0392b;">报销审批提醒（{stage_cn}）</h2>
      <p>您有一张报销单待审批，请及时处理：</p>
      <table style="border-collapse:collapse;">
        <tr><td style="padding:4px 12px;color:#888;">报销单号</td><td style="padding:4px 12px;"><b>{reimb.id}</b></td></tr>
        <tr><td style="padding:4px 12px;color:#888;">申请人</td><td style="padding:4px 12px;">{reimb.user_name}（{reimb.department}）</td></tr>
        <tr><td style="padding:4px 12px;color:#888;">费用类型</td><td style="padding:4px 12px;">{reimb.expense_type}</td></tr>
        <tr><td style="padding:4px 12px;color:#888;">金额</td><td style="padding:4px 12px;color:#c0392b;"><b>¥{total:,.2f}</b></td></tr>
        <tr><td style="padding:4px 12px;color:#888;">标题</td><td style="padding:4px 12px;">{reimb.title or '—'}</td></tr>
      </table>
      <p>报销单 PDF 见附件。请登录系统进行审批。</p>
      <p style="color:#aaa;font-size:12px;">本邮件由报销系统自动发送，请勿直接回复。</p>
    </div>
    """
    return subject, body


async def _pdf_bytes_for(reimb) -> tuple[bytes | None, str]:
    """为报销单生成 PDF 并取回二进制内容（用于邮件附件）。失败返回 (None, "")。"""
    from app.services.pdf_svc import generate_and_store_reimbursement_pdf
    from app.services.ocr_svc import get_file_content
    try:
        info = await generate_and_store_reimbursement_pdf(reimb)
        object_name = info.get("object_name", "")
        if not object_name:
            return None, ""
        content = await get_file_content(object_name)
        return content, f"报销单_{reimb.id[:8]}.pdf"
    except Exception as e:
        logger.warning(f"通知邮件生成/读取 PDF 失败（不阻断）: {e}")
        return None, ""


async def send_reimbursement_notification(reimb_id: str, stage: str) -> dict:
    """给指定阶段的审批人发送报销单待审批邮件（附 PDF）。尽力而为，绝不抛异常。

    stage: "manager"（一审·部门经理）或 "finance"（二审·财务）。
    """
    if stage not in _STAGE_TARGET:
        logger.warning(f"未知通知阶段: {stage}")
        return {"sent": 0, "recipients": []}
    target_role, stage_cn = _STAGE_TARGET[stage]

    try:
        from app.services.expense_sheet_svc import ExpenseSheetService
        async with AsyncSessionLocal() as db:
            reimb = await ExpenseSheetService(db).get(reimb_id)
            department = reimb.department if target_role == "manager" else None
            recipients = await resolve_role_emails(db, target_role, department)
            subject, body = _build_email(reimb, stage_cn)
            pdf_bytes, pdf_name = await _pdf_bytes_for(reimb)

        if not recipients:
            logger.warning(
                f"通知跳过：未找到{stage_cn}的收件邮箱 "
                f"(role={target_role}, dept={department or '不限'}, reimb={reimb_id})"
            )
            return {"sent": 0, "recipients": []}

        from app.services.email_svc import send_email
        sent = 0
        ok_list = []
        for r in recipients:
            ok = await send_email(
                r["email"], subject, body,
                attachment_bytes=pdf_bytes, attachment_name=pdf_name,
            )
            if ok:
                sent += 1
                ok_list.append(r["email"])
        logger.info(f"审批通知已发送: {stage_cn} reimb={reimb_id} 成功 {sent}/{len(recipients)} → {ok_list}")
        return {"sent": sent, "recipients": [r["email"] for r in recipients]}
    except Exception as e:
        logger.error(f"发送审批通知失败（不阻断业务）: reimb={reimb_id} stage={stage} err={e}")
        return {"sent": 0, "recipients": [], "error": str(e)}


def dispatch_reimbursement_notification(reimb_id: str, stage: str) -> None:
    """以后台任务方式发送通知（fire-and-forget），不阻塞调用方。

    在已有事件循环中用 create_task；异常已在内部捕获，绝不影响主流程。
    """
    async def _bg():
        await send_reimbursement_notification(reimb_id, stage)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_bg())
    except RuntimeError:
        # 无运行中的事件循环（极少见，如同步上下文）：直接运行
        try:
            asyncio.run(_bg())
        except Exception as e:
            logger.warning(f"后台通知发送失败: {e}")
