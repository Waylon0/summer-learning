"""
=============================================================================
app/services/notification_svc.py — 报销审批邮件通知（鲁棒版）
=============================================================================
核心思路（SMTP 与"发给不同用户"）:
  - SMTP 账号只是【固定的认证发件人】(From)；收件人 To 可为【任意】邮箱。
  - "发给不同用户" = 从 users 表按"角色(+部门)"查出目标用户 email 作为 To。

收件规则（两阶段审批）:
  1. 提交成功  → 通知【申请人所在部门的所有部门经理】进行一审；
  2. 一审通过  → 通知【所有财务】进行二审；
  3. 无论一审二审，都额外【抄送所有管理员】（若其有可用邮箱）。

鲁棒性设计:
  - 邮箱先做【格式校验】，再逐个投递；无邮箱/格式非法/发送失败的收件人自动【跳过】，
    绝不因个别收件人失败而漏发其他人。
  - "成功"判定：只要【主审角色】(经理/财务) 至少 1 人送达即视为成功；否则视为失败，
    由上层（Agent）据实告知用户，并可让用户稍后【重发】。
  - 全程尽力而为，任何异常只记日志、不打断报销提交/审批主流程。
=============================================================================
"""
from __future__ import annotations

import re
import asyncio

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.approval_rules import STEP_MANAGER, STEP_FINANCE
from app.models.user import User


# 阶段 → (主审目标角色, 中文阶段名)
_STAGE_TARGET = {
    "manager": ("manager", "一审（部门经理）"),
    "finance": ("finance", "二审（财务）"),
}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email: str) -> bool:
    """基础邮箱格式校验（用于投递前过滤明显无效地址）。"""
    e = (email or "").strip()
    return bool(e) and bool(_EMAIL_RE.match(e))


def can_resend(stage: str, user_role: str, user_id: str, reimb_user_id: str,
               user_dept: str, reimb_dept: str) -> bool:
    """判断当前用户是否有权重发某阶段通知（纯函数，便于单测）。

    - admin：任意；
    - 一审(manager)：申请人本人 或 本部门经理；
    - 二审(finance)：财务 或 本部门经理（其已完成一审）。
    """
    r = (user_role or "").lower()
    if r == "admin":
        return True
    if stage == "manager":
        return (user_id == reimb_user_id) or (r == "manager" and user_dept == reimb_dept)
    if stage == "finance":
        return (r == "finance") or (r == "manager" and user_dept == reimb_dept)
    return False


async def resolve_role_emails(
    db: AsyncSession, role: str, department: str | None = None
) -> list[dict]:
    """查出某角色（可限定部门）下所有【启用且邮箱格式有效】的用户。

    返回 [{name, email, department}]，邮箱经过格式校验；无邮箱/非法者被跳过。
    """
    conds = [User.role == role, User.is_active == True]  # noqa: E712
    if department:
        conds.append(User.department == department)
    rows = (await db.execute(select(User).where(*conds))).scalars().all()
    result = []
    for u in rows:
        email = (u.email or "").strip()
        if is_valid_email(email):
            result.append({"name": u.name, "email": email, "department": u.department})
        elif email:
            logger.info(f"跳过格式非法的邮箱: user={u.username} email={email!r}")
    return result


def infer_current_stage(reimb) -> str | None:
    """由报销单当前最早的 pending 审批步骤，推断当前处于哪个阶段。

    返回 "manager" / "finance" / None（无待审批步骤）。需 reimb.approvals 已加载。
    """
    pend = sorted(
        [a for a in (reimb.approvals or []) if a.action == "pending"],
        key=lambda a: a.step,
    )
    if not pend:
        return None
    title = pend[0].approver
    if title == STEP_MANAGER:
        return "manager"
    if title == STEP_FINANCE:
        return "finance"
    return None


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
    """给指定阶段的审批人发送待审批邮件（附 PDF），并抄送所有管理员。尽力而为，绝不抛异常。

    stage: "manager"（一审·部门经理）或 "finance"（二审·财务）。

    返回结构（供上层向用户报告）:
      {
        success: bool,          # 主审角色是否至少 1 人送达
        stage, stage_cn,
        primary_total: int,     # 主审角色可投递收件人数（有效邮箱）
        primary_delivered: int, # 主审角色实际送达数
        admin_delivered: int,   # 管理员抄送送达数
        delivered: [邮箱...], failed: [邮箱...],
        reason: str,            # 失败原因（success=False 时）
      }
    """
    if stage not in _STAGE_TARGET:
        logger.warning(f"未知通知阶段: {stage}")
        return {"success": False, "stage": stage, "reason": "未知通知阶段",
                "primary_total": 0, "primary_delivered": 0, "admin_delivered": 0,
                "delivered": [], "failed": []}
    target_role, stage_cn = _STAGE_TARGET[stage]

    try:
        from app.services.expense_sheet_svc import ExpenseSheetService
        async with AsyncSessionLocal() as db:
            reimb = await ExpenseSheetService(db).get(reimb_id)
            department = reimb.department if target_role == "manager" else None
            primary = await resolve_role_emails(db, target_role, department)
            admins = await resolve_role_emails(db, "admin", None)
            subject, body = _build_email(reimb, stage_cn)
            pdf_bytes, pdf_name = await _pdf_bytes_for(reimb)

        # 管理员抄送去重（排除已在主审列表中的同一邮箱）
        primary_emails = {r["email"].lower() for r in primary}
        admin_cc = []
        seen = set(primary_emails)
        for a in admins:
            key = a["email"].lower()
            if key not in seen:
                admin_cc.append(a)
                seen.add(key)

        from app.services.email_svc import send_email
        delivered, failed = [], []
        primary_delivered = 0
        for r in primary:
            ok = await send_email(r["email"], subject, body,
                                  attachment_bytes=pdf_bytes, attachment_name=pdf_name)
            if ok:
                delivered.append(r["email"]); primary_delivered += 1
            else:
                failed.append(r["email"])
        admin_delivered = 0
        for a in admin_cc:
            ok = await send_email(a["email"], subject, body,
                                  attachment_bytes=pdf_bytes, attachment_name=pdf_name)
            if ok:
                delivered.append(a["email"]); admin_delivered += 1
            else:
                failed.append(a["email"])

        success = primary_delivered >= 1
        reason = ""
        if not success:
            if not primary:
                reason = f"未找到{stage_cn}的可用收件邮箱（相关审批人未绑定邮箱或邮箱格式无效）"
            else:
                reason = f"{stage_cn}收件邮箱发送均失败（请检查 SMTP 配置或邮箱有效性）"

        logger.info(
            f"审批通知[{stage_cn}] reimb={reimb_id}: 主审送达 {primary_delivered}/{len(primary)}，"
            f"管理员抄送送达 {admin_delivered}/{len(admin_cc)}，success={success}"
            + (f"，原因：{reason}" if reason else "")
        )
        return {
            "success": success, "stage": stage, "stage_cn": stage_cn,
            "primary_total": len(primary), "primary_delivered": primary_delivered,
            "admin_delivered": admin_delivered,
            "delivered": delivered, "failed": failed, "reason": reason,
        }
    except Exception as e:
        logger.error(f"发送审批通知异常（不阻断业务）: reimb={reimb_id} stage={stage} err={e}")
        return {"success": False, "stage": stage, "stage_cn": stage_cn,
                "primary_total": 0, "primary_delivered": 0, "admin_delivered": 0,
                "delivered": [], "failed": [], "reason": f"发送异常：{e}"}


def dispatch_reimbursement_notification(reimb_id: str, stage: str) -> None:
    """以后台任务方式发送通知（fire-and-forget），不阻塞调用方（供 REST 端点使用）。

    Agent 侧改为【同步 await】以便向用户反馈发送结果（见 agent_tools）。
    """
    async def _bg():
        await send_reimbursement_notification(reimb_id, stage)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_bg())
    except RuntimeError:
        try:
            asyncio.run(_bg())
        except Exception as e:
            logger.warning(f"后台通知发送失败: {e}")
