"""
=============================================================================
app/agent/agent_tools.py — ReAct Agent 工具集（LangChain @tool）
=============================================================================
把报销业务能力暴露为 LLM 可自主调用的工具。LLM 依据用户自然语言，
自行决定调用哪个工具、传什么参数、多轮调用组合，充分理解用户意图。

安全与上下文注入:
  - 当前登录用户（id/姓名/部门/角色）与本轮上传附件，通过 contextvars 注入，
    工具内部读取，不暴露给 LLM，杜绝越权/伪造。
  - 查询/开票/审批等均按角色做权限收窄（员工本人 / 经理本部门 / 管理员全部）。

工具清单:
  1. get_current_user_context   — 获取当前用户信息（部门/角色）
  2. get_expense_policy         — RAG 检索费用政策/标准/流程（增强，不做意图理解）
  3. get_department_budget      — 查询部门预算余额
  4. check_expense_compliance   — 校验金额是否合规
  5. query_reimbursements       — 多维度查询报销单（安全 + 权限）
  6. ocr_uploaded_invoices      — OCR 识别本轮上传的发票，返回结构化信息与金额
  7. submit_reimbursement       — 提交报销（合规+预算+入库+PDF+邮件一条龙）
  8. generate_reimbursement_pdf_doc — 为已有报销单生成报销单 PDF
  9. approve_reimbursement      — 审批（通过/驳回/退回）
=============================================================================
"""
from __future__ import annotations

import contextvars
from typing import Optional

from langchain_core.tools import tool
from loguru import logger

# ---- 每轮请求的上下文（用户 + 附件），由 chat 层设置 ----
_current_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar("agent_ctx", default={})


def set_agent_context(*, user_id: str, user_name: str, user_role: str,
                      user_department: str, attachments: list[str] | None = None) -> None:
    _current_ctx.set({
        "user_id": user_id or "",
        "user_name": user_name or "",
        "user_role": (user_role or "").lower(),
        "user_department": user_department or "",
        "attachments": attachments or [],
    })


def _ctx() -> dict:
    return _current_ctx.get() or {}


# =============================================================================
# 1. 当前用户信息
# =============================================================================
@tool
async def get_current_user_context() -> dict:
    """获取当前登录用户的信息（用户ID、姓名、所属部门、角色）。
    当需要知道"我是谁""我的部门"或为报销填充默认部门时调用。"""
    c = _ctx()
    return {
        "user_name": c.get("user_name", ""),
        "department": c.get("user_department", ""),
        "role": c.get("user_role", ""),
        "has_uploaded_files": bool(c.get("attachments")),
        "uploaded_file_count": len(c.get("attachments", [])),
    }


# =============================================================================
# 2. RAG 政策检索（知识库增强，不做意图理解）
# =============================================================================
@tool
async def get_expense_policy(query: str) -> str:
    """检索公司报销政策知识库，返回与问题最相关的政策原文片段。
    适用于：费用标准/限额、报销流程、部门额度、发票要求等政策类问题。
    参数 query 为用户的政策问题（自然语言）。"""
    from app.agent.knowledge.retriever import build_context_for_llm
    from app.agent.knowledge.loader import get_or_build_index
    try:
        get_or_build_index()
    except Exception:
        pass
    ctx = build_context_for_llm(query, top_k=3)
    if not ctx or len(ctx) < 10:
        return "知识库中未找到直接相关的政策条款，建议提示用户咨询财务部获取最新政策。"
    return ctx


# =============================================================================
# 3. 部门预算
# =============================================================================
@tool
async def get_department_budget(department: str = "") -> dict:
    """查询某部门的年度预算与剩余余额。department 留空则查询当前用户所属部门。"""
    from app.agent.tools.reimburse_tools import budget_check
    dept = department or _ctx().get("user_department", "")
    if not dept:
        return {"available": False, "message": "无法确定部门，请提供部门名称。"}
    result = await budget_check(department=dept, amount=0)
    return result


# =============================================================================
# 4. 合规校验
# =============================================================================
@tool
async def check_expense_compliance(expense_type: str, total_amount: float, department: str = "") -> dict:
    """校验一笔报销金额是否符合公司费用标准（限额）。
    expense_type: travel/entertainment/office/other 等；total_amount: 金额。"""
    from app.agent.tools.reimburse_tools import compliance_check
    dept = department or _ctx().get("user_department", "")
    return await compliance_check(expense_type=expense_type, total_amount=total_amount, department=dept)


# =============================================================================
# 5. 查询报销单（安全 + 权限）
# =============================================================================
@tool
async def query_reimbursements(
    status: str = "",
    department: str = "",
    expense_type: str = "",
    user_name: str = "",
    amount_min: Optional[float] = None,
    amount_max: Optional[float] = None,
    keyword: str = "",
    reimb_id: str = "",
    limit: int = 20,
) -> dict:
    """查询报销单，支持任意组合筛选：状态(pending/approved/rejected/returned/paid)、
    部门、费用类型、申请人姓名、金额区间、关键词、报销单号。
    权限自动收窄：员工仅本人、经理仅本部门、管理员/财务全部。
    若提供 reimb_id 则返回该单详情与审批流程。"""
    from app.core.database import AsyncSessionLocal
    from app.agent.query_planner import sanitize_plan, execute_plan
    from app.agent.tools.reimburse_tools import query_reimbursement_status

    c = _ctx()
    uid, role, dept = c.get("user_id", ""), c.get("user_role", ""), c.get("user_department", "")

    # 单号详情：查完后做归属权限校验
    if reimb_id:
        result = await query_reimbursement_status(reimb_id=reimb_id)
        if result.get("status") in ("not_found", "unknown"):
            return {"found": False, "message": f"未找到报销单 {reimb_id}"}
        owner_uid, owner_dept = result.get("user_id", ""), result.get("department", "")
        if role == "employee" and owner_uid and owner_uid != uid:
            return {"found": False, "message": "无权查看他人的报销单"}
        if role == "manager" and owner_dept and owner_dept != dept:
            return {"found": False, "message": f"无权查看 {owner_dept} 的报销单"}
        return {"found": True, "detail": result}

    raw = {
        "status": status or None, "department": department or None,
        "expense_type": expense_type or None, "user_name": user_name or None,
        "amount_min": amount_min, "amount_max": amount_max,
        "keyword": keyword or None, "limit": limit,
    }
    plan = sanitize_plan(raw)
    async with AsyncSessionLocal() as db:
        records, total, notice = await execute_plan(
            db, plan, user_id=uid, user_role=role, user_department=dept
        )
    return {"total": total, "count": len(records), "records": records, "notice": notice}


# =============================================================================
# 6. OCR 识别本轮上传发票
# =============================================================================
@tool
async def ocr_uploaded_invoices() -> dict:
    """识别用户本轮上传的发票文件，返回每张发票的结构化信息（金额、销售方、日期等）
    及汇总金额。当用户上传了票据并想据此报销时调用。"""
    from app.agent.tools.reimburse_tools import ocr_recognize_invoice
    attachments = _ctx().get("attachments", [])
    if not attachments:
        return {"has_files": False, "invoices": [], "total_amount": 0.0,
                "message": "本轮没有检测到上传的发票文件。"}
    invoices, total = [], 0.0
    for path in attachments:
        try:
            r = await ocr_recognize_invoice(path)
            if r.get("amount", 0) > 0:
                invoices.append(r)
                total += float(r.get("amount", 0) or 0)
        except Exception as e:
            logger.warning(f"OCR failed for {path}: {e}")
    return {
        "has_files": True,
        "invoice_count": len(invoices),
        "total_amount": round(total, 2),
        "invoices": invoices,
        "message": f"识别到 {len(invoices)} 张发票，合计 ¥{total:,.2f}" if invoices else "上传的文件未能识别出有效发票。",
    }


# =============================================================================
# 7. 提交报销（合规 + 预算 + 入库 + PDF + 邮件）
# =============================================================================
@tool
async def submit_reimbursement(
    expense_type: str,
    total_amount: float,
    department: str = "",
    description: str = "",
    invoices: Optional[list] = None,
) -> dict:
    """提交一笔报销申请（会自动完成：合规校验 → 预算检查 → 入库 → 生成报销单PDF）。
    仅在已确认费用类型和金额后调用。
    参数:
      expense_type: 费用类型 travel/entertainment/office/other 等
      total_amount: 报销总金额（必须 > 0）
      department: 部门（留空用当前用户部门）
      description: 报销说明
      invoices: 可选，发票明细列表（通常来自 ocr_uploaded_invoices 的结果）
    返回是否成功、报销单号、是否超标、PDF 下载地址等。"""
    from app.agent.tools.reimburse_tools import (
        compliance_check, budget_check, save_reimbursement_to_db,
    )
    from app.core.database import AsyncSessionLocal
    from app.services.reimbursement_svc import ReimbursementService
    from app.services.pdf_svc import generate_and_store_reimbursement_pdf

    c = _ctx()
    uid = c.get("user_id", "")
    uname = c.get("user_name", "") or "未知用户"
    dept = department or c.get("user_department", "")

    if not uid:
        return {"success": False, "message": "您尚未登录，无法提交报销。"}
    if not total_amount or float(total_amount) <= 0:
        return {"success": False, "message": "报销金额必须大于 0，请先确认金额。"}
    if not dept:
        return {"success": False, "message": "缺少部门信息，无法提交。"}

    # 合规
    comp = await compliance_check(expense_type=expense_type, total_amount=float(total_amount), department=dept)
    # 预算
    bud = await budget_check(department=dept, amount=float(total_amount))
    if not bud.get("available", True):
        return {"success": False, "message": bud.get("message", "预算数据不可用，暂无法提交。")}
    need_special = bud.get("need_special_approval", False)
    budget_after = bud.get("after_reimbursement", 0)

    inv_list = invoices or []
    try:
        result = await save_reimbursement_to_db(
            department=dept, expense_type=expense_type, total_amount=float(total_amount),
            invoices=inv_list, need_special_approval=need_special,
            budget_remaining_after=budget_after, description=description,
            user_id=uid, user_name=uname,
        )
    except Exception as e:
        logger.error(f"submit_reimbursement 入库失败: {e}")
        return {"success": False, "message": "报销单保存失败，请稍后重试。"}

    reimb_id = result.get("reimb_id", "")
    # 生成 PDF（失败不阻断）
    download_url = ""
    try:
        async with AsyncSessionLocal() as db:
            svc = ReimbursementService(db)
            reimb = await svc.get_by_id(reimb_id)
            info = await generate_and_store_reimbursement_pdf(reimb)
            download_url = info.get("download_url", "")
    except Exception as e:
        logger.warning(f"报销单 PDF 生成失败（不阻断）: {e}")

    return {
        "success": True,
        "reimb_id": reimb_id,
        "department": dept,
        "expense_type": expense_type,
        "total_amount": float(total_amount),
        "need_special_approval": need_special,
        "compliance": comp,
        "budget_remaining_after": budget_after,
        "pdf_download_url": download_url,
        "message": "报销单已提交，进入审批流程。" + ("（预算超标，需特殊审批）" if need_special else ""),
    }


# =============================================================================
# 8. 为已有报销单生成 PDF
# =============================================================================
@tool
async def generate_reimbursement_pdf_doc(reimb_id: str) -> dict:
    """为一张【已存在】的报销单生成结构化报销单 PDF 并返回下载地址。
    需提供报销单号 reimb_id。权限：员工仅本人、经理仅本部门。"""
    from app.core.database import AsyncSessionLocal
    from app.services.reimbursement_svc import ReimbursementService
    from app.services.pdf_svc import generate_and_store_reimbursement_pdf
    from app.core.exceptions import ReimbursementNotFoundError

    c = _ctx()
    uid, role, dept = c.get("user_id", ""), c.get("user_role", ""), c.get("user_department", "")
    async with AsyncSessionLocal() as db:
        svc = ReimbursementService(db)
        try:
            reimb = await svc.get_by_id(reimb_id)
        except ReimbursementNotFoundError:
            return {"success": False, "message": f"未找到报销单 {reimb_id}"}
        if role == "employee" and reimb.user_id != uid:
            return {"success": False, "message": "只能为本人的报销单生成 PDF"}
        if role == "manager" and reimb.department != dept:
            return {"success": False, "message": f"只能为本部门（{dept}）的报销单生成 PDF"}
        try:
            info = await generate_and_store_reimbursement_pdf(reimb)
        except Exception as e:
            logger.error(f"生成报销单 PDF 失败: {e}")
            return {"success": False, "message": "报销单 PDF 生成失败，请稍后重试。"}
    return {"success": True, "reimb_id": reimb_id,
            "pdf_download_url": info.get("download_url", ""),
            "message": "报销单 PDF 已生成。"}


# =============================================================================
# 9. 审批
# =============================================================================
@tool
async def approve_reimbursement(reimb_id: str, action: str, comment: str = "") -> dict:
    """审批一张报销单。action: approve(通过)/reject(驳回)/return(退回)。
    权限：仅经理(限本部门)、管理员、财务可操作。"""
    from app.core.database import AsyncSessionLocal
    from app.services.reimbursement_svc import ApprovalService
    from app.models.reimbursement import Reimbursement
    from app.core.exceptions import ReimbursementNotFoundError, BusinessException

    c = _ctx()
    uname, role, dept = c.get("user_name", "") or "审批人", c.get("user_role", ""), c.get("user_department", "")
    if role not in ("manager", "admin", "finance"):
        return {"success": False, "message": "您没有审批权限，只有经理或管理员可审批。"}
    action = (action or "").lower()
    if action not in ("approve", "reject", "return"):
        return {"success": False, "message": "无效的审批动作，应为 approve/reject/return。"}

    async with AsyncSessionLocal() as db:
        reimb = await db.get(Reimbursement, reimb_id)
        if not reimb:
            return {"success": False, "message": f"未找到报销单 {reimb_id}"}
        if role == "manager" and reimb.department != dept:
            return {"success": False, "message": f"只能审批本部门（{dept}）的报销单。"}
        if reimb.status != "pending":
            return {"success": False, "message": f"该报销单当前状态为 {reimb.status}，只有待审批的才能审批。"}
        svc = ApprovalService(db)
        try:
            await svc.record(reimb_id, uname, action, comment or None)
        except (ReimbursementNotFoundError, BusinessException) as e:
            return {"success": False, "message": e.message}
        except Exception as e:
            logger.error(f"审批失败: {e}")
            return {"success": False, "message": "审批操作失败，请稍后重试。"}
    cn = {"approve": "已通过", "reject": "已驳回", "return": "已退回"}[action]
    return {"success": True, "reimb_id": reimb_id, "result": cn, "message": f"报销单 {reimb_id} {cn}。"}


AGENT_TOOLS = [
    get_current_user_context,
    get_expense_policy,
    get_department_budget,
    check_expense_compliance,
    query_reimbursements,
    ocr_uploaded_invoices,
    submit_reimbursement,
    generate_reimbursement_pdf_doc,
    approve_reimbursement,
]
