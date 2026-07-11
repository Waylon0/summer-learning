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
  --- 分步式报销（企业级：草稿→逐条明细→校验→提交）---
  7. start_reimbursement_draft  — 创建报销单草稿
  8. add_expense_item           — 逐条添加费用明细（自动判定发票/补贴）
  9. remove_expense_item        — 删除明细
  10. attach_invoice            — 为明细行关联发票
  11. view_reimbursement_draft  — 查看草稿（分类小计/明细/缺票项）
  12. submit_reimbursement      — 严格校验后提交进入审批
  13. generate_reimbursement_pdf_doc — 为已有报销单生成报销单 PDF
  14. approve_reimbursement     — 审批（通过/驳回/退回）
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
    qr_count = 0
    for path in attachments:
        try:
            r = await ocr_recognize_invoice(path)
            if r.get("amount", 0) > 0:
                invoices.append(r)
                total += float(r.get("amount", 0) or 0)
                if r.get("qr_verified"):
                    qr_count += 1
        except Exception as e:
            logger.warning(f"OCR failed for {path}: {e}")
    qr_note = f"（其中 {qr_count} 张已通过增值税发票二维码验真）" if qr_count else ""
    return {
        "has_files": True,
        "invoice_count": len(invoices),
        "total_amount": round(total, 2),
        "invoices": invoices,
        "message": (
            f"识别到 {len(invoices)} 张发票{qr_note}，合计 ¥{total:,.2f}。"
            f"这是【本轮上传】的发票，请关联到当前草稿的对应明细（attach_invoice），"
            f"用完后不得跨其他报销单混用。"
            if invoices else "上传的文件未能识别出有效发票。"
        ),
    }


# =============================================================================
# 7. 分步式报销（企业级：草稿 → 逐条明细 → 校验 → 提交）
# =============================================================================
def _fmt_sheet(reimb) -> dict:
    """把报销单渲染成便于 LLM 转述的结构（含分类小计、明细、缺票项）。"""
    from collections import defaultdict
    from app.agent import expense_rules as rules

    items = sorted(reimb.items or [], key=lambda x: x.seq)
    cat_subtotal: dict[str, float] = defaultdict(float)
    lines = []
    for it in items:
        cat_subtotal[it.category] += float(it.amount or 0)
        flag = "补贴(免票)" if it.is_subsidy else ("待补发票" if (it.needs_invoice and not it.has_invoice) else ("已附票" if it.has_invoice else "免票"))
        lines.append({
            "seq": it.seq,
            "category": rules.category_label(it.category),
            "subtype": rules.subtype_label(it.subtype),
            "description": it.description or "",
            "amount": float(it.amount or 0),
            "unit_price": float(it.unit_price) if it.unit_price is not None else None,
            "quantity": float(it.quantity) if it.quantity is not None else None,
            "unit": it.unit or "",
            "evidence": flag,
            "remark": it.remark or "",
            "attendee_count": it.attendee_count,
            "guest_info": it.guest_info or "",
            "currency": it.currency or "CNY",
            "original_amount": float(it.original_amount) if it.original_amount is not None else None,
        })
    subtotals = [{"category": rules.category_label(c), "amount": round(a, 2)} for c, a in cat_subtotal.items()]
    return {
        "reimb_id": reimb.id,
        "title": reimb.title or "",
        "status": reimb.status,
        "trip_destination": reimb.trip_destination or "",
        "trip_days": reimb.trip_days,
        "total_amount": float(reimb.total_amount or 0),
        "invoice_amount": float(reimb.invoice_amount or 0),
        "invoiced_amount": float(getattr(reimb, "invoiced_amount", 0) or 0),
        "subsidy_amount": float(reimb.subsidy_amount or 0),
        "tax_amount": float(getattr(reimb, "tax_amount", 0) or 0),
        "item_count": len(items),
        "category_subtotals": subtotals,
        "items": lines,
    }


@tool
async def start_reimbursement_draft(
    expense_type: str = "travel",
    title: str = "",
    trip_destination: str = "",
    trip_start_date: str = "",
    trip_end_date: str = "",
    description: str = "",
    force_new: bool = False,
) -> dict:
    """创建一张【报销单草稿】，作为后续逐条添加费用明细的容器。
    差旅报销请尽量填 trip_destination（目的地）、trip_start_date/trip_end_date（YYYY-MM-DD 出差起止日）。
    一次完整的出差/事项对应【一张】草稿，然后多次调用 add_expense_item 往里加明细。

    草稿隔离规则（重要，防止把两件事的报销混到一张单里）：
      - 若用户【没有】未提交草稿，或仅有一张【空】草稿（0 条明细）→ 直接创建/复用，返回其 reimb_id。
      - 若用户已有一张【含明细】的未提交草稿，且 force_new 未设 → 【不自动复用也不自动新建】，
        而是返回 needs_confirmation=True 与该草稿摘要；你必须先【询问用户】：
        "继续完善这张旧草稿，还是新建一张？"
          · 用户要继续 → 用返回的 existing_reimb_id 继续 add_expense_item；
          · 用户要新建 → 再次调用本工具并传 force_new=True。
    返回草稿 reimb_id 及当前状态。后续该报销单的所有明细/发票/预览/提交，
    都要使用【同一个 reimb_id】，不要与其他草稿混用。"""
    from app.core.database import AsyncSessionLocal
    from app.services.expense_sheet_svc import ExpenseSheetService

    c = _ctx()
    if not c.get("user_id"):
        return {"success": False, "message": "您尚未登录，无法创建报销单。"}
    async with AsyncSessionLocal() as db:
        svc = ExpenseSheetService(db)
        if not force_new:
            existing = await svc.find_active_draft(c["user_id"])
            if existing is not None:
                sheet = _fmt_sheet(existing)
                item_count = sheet["item_count"]
                if item_count == 0:
                    # 空草稿：直接复用，避免产生重复空单（不打扰用户）
                    return {
                        "success": True, "existing": True, "reimb_id": existing.id,
                        "needs_confirmation": False, "sheet": sheet,
                        "message": "已有一张空白草稿，继续为您使用它，请逐条添加费用明细。",
                    }
                # 含明细的旧草稿：必须让用户决定，绝不自动合并到旧单
                return {
                    "success": True, "existing": True, "needs_confirmation": True,
                    "existing_reimb_id": existing.id, "sheet": sheet,
                    "message": (
                        f"您还有一张【未提交】的报销单草稿（reimb_id={existing.id}，标题「{sheet['title'] or '未命名'}」，"
                        f"已含 {item_count} 条明细、合计 ¥{sheet['total_amount']:,.2f}）。\n"
                        f"请问您是要【继续完善这张旧草稿】，还是【新建一张报销单】？\n"
                        f"（继续→我在这张上加；新建→我另开一张，两张互不影响。请勿把不同事项混在一张单里。）"
                    ),
                }
        reimb = await svc.create_draft(
            user_id=c["user_id"], user_name=c.get("user_name", ""),
            department=c.get("user_department", ""),
            expense_type=expense_type or "travel", title=title,
            trip_destination=trip_destination, trip_start_date=trip_start_date,
            trip_end_date=trip_end_date, description=description,
        )
        sheet = _fmt_sheet(reimb)
    return {"success": True, "existing": False, "needs_confirmation": False,
            "reimb_id": sheet["reimb_id"], "sheet": sheet,
            "message": f"已创建新的报销单草稿（reimb_id={sheet['reimb_id']}），"
                       f"请逐条添加费用明细（交通/住宿/餐饮等）。后续都用这个 reimb_id 操作本单。"}


@tool
async def list_my_drafts() -> dict:
    """列出当前用户【所有未提交的报销单草稿】（各自 reimb_id、标题、明细数、金额）。
    当用户有多张草稿、需要选择在哪一张上继续操作，或想确认草稿彼此隔离时调用。
    用于避免把不同事项的费用混到同一张单里。"""
    from app.core.database import AsyncSessionLocal
    from app.models.reimbursement import Reimbursement
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    c = _ctx()
    uid = c.get("user_id", "")
    if not uid:
        return {"success": False, "message": "您尚未登录。"}
    async with AsyncSessionLocal() as db:
        stmt = (
            select(Reimbursement)
            .options(selectinload(Reimbursement.items))
            .where(Reimbursement.user_id == uid, Reimbursement.status == "draft")
            .order_by(Reimbursement.updated_at.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()
        drafts = [{
            "reimb_id": r.id,
            "title": r.title or "未命名",
            "expense_type": r.expense_type,
            "item_count": len(r.items or []),
            "total_amount": float(r.total_amount or 0),
            "trip_destination": r.trip_destination or "",
            "updated_at": r.updated_at.isoformat() if r.updated_at else "",
        } for r in rows]
    return {
        "success": True, "count": len(drafts), "drafts": drafts,
        "message": (
            f"您有 {len(drafts)} 张未提交的草稿，请让用户确认在哪一张上继续，或新建一张。"
            if len(drafts) > 1 else
            (f"您有 1 张未提交的草稿（reimb_id={drafts[0]['reimb_id']}）。" if drafts
             else "您当前没有未提交的草稿。")
        ),
    }


@tool
async def add_expense_item(
    reimb_id: str,
    subtype: str,
    amount: float = 0,
    unit_price: float = 0,
    quantity: float = 0,
    description: str = "",
    occur_date: str = "",
    from_location: str = "",
    to_location: str = "",
    remark: str = "",
    attendee_count: int = 0,
    guest_info: str = "",
    currency: str = "CNY",
    exchange_rate: float = 0,
) -> dict:
    """向报销单草稿添加一条费用明细。系统会自动判断该笔是否【必须发票】或【按补贴发放】。

    subtype 常用值（大类:子类）:
      城际交通: flight(机票)/train(火车票)/coach(长途汽车)
      市内交通: taxi(打车)/metro_bus(地铁公交)/parking(停车)/fuel(油费)
      住宿: hotel(酒店)
      餐饮: meal_allowance(餐补)/business_meal(商务宴请)
      其他差旅: baggage(行李)/visa(签证)/travel_insurance(差旅保险)
      招待: banquet(宴请)/gift(礼品)  办公: stationery/equipment  通信: phone_bill  培训: training_fee  其他: misc
    也可传中文（如"机票""酒店""打车"），系统会归一化。

    金额填写二选一：
      - 单价×数量：填 unit_price + quantity（如住宿 unit_price=500, quantity=3 表示 3 晚；餐补 unit_price=150, quantity=4 表示 4 天）
      - 直接总额：填 amount（如机票 amount=1200）
    可选 occur_date（YYYY-MM-DD）、from_location/to_location（交通的出发/到达地）。

    超标规则（重要）：住宿(≤500/晚)、餐补(≤150/天)、话费(≤200/月)等有单位上限；
    若单价超过标准，必须在 remark 里填写"超标说明"（如"会议指定酒店"），否则提交会被拒绝；
    填了说明也会转为特殊审批。切勿为绕过上限而擅自压低单价。

    招待类（banquet 宴请 / business_meal 商务宴请）：请尽量登记 attendee_count（招待人数）
    与 guest_info（招待对象/事由）；人均超过 ¥200 需在 remark 填写超标说明，否则提交会被拒绝。

    外币报销：若费用为外币，请传 currency（如 USD/JPY/EUR）与 exchange_rate（1 外币=?人民币），
    系统会折算为人民币入账；人民币可不填（默认 CNY）。

    返回该明细是否需要发票、当前报销单汇总。"""
    from app.core.database import AsyncSessionLocal
    from app.services.expense_sheet_svc import ExpenseSheetService
    from app.core.exceptions import BusinessException, ReimbursementNotFoundError

    c = _ctx()
    async with AsyncSessionLocal() as db:
        svc = ExpenseSheetService(db)
        # 权限：只能改自己的草稿
        try:
            reimb0 = await svc.get(reimb_id)
        except ReimbursementNotFoundError:
            return {"success": False, "message": f"未找到报销单 {reimb_id}"}
        if reimb0.user_id != c.get("user_id"):
            return {"success": False, "message": "只能编辑本人的报销单。"}
        try:
            reimb, item = await svc.add_item(
                reimb_id, subtype=subtype, amount=amount,
                unit_price=unit_price, quantity=quantity, description=description,
                occur_date=occur_date, from_location=from_location, to_location=to_location,
                remark=remark, attendee_count=attendee_count, guest_info=guest_info,
                currency=currency, exchange_rate=exchange_rate,
            )
        except BusinessException as e:
            return {"success": False, "message": e.message}
        sheet = _fmt_sheet(reimb)
    tip = ("该笔为大额/必须凭票项，请提供发票（可稍后用 attach_invoice 关联，或上传后调用 ocr_uploaded_invoices）。"
           if item.needs_invoice and not item.has_invoice
           else "该笔按补贴发放，无需发票。" if item.is_subsidy else "该笔已记录。")
    return {"success": True, "item_seq": item.seq,
            "needs_invoice": item.needs_invoice, "is_subsidy": item.is_subsidy,
            "sheet": sheet, "message": tip}


@tool
async def update_expense_item(
    reimb_id: str,
    item_seq: int,
    subtype: str = "",
    amount: float = 0,
    unit_price: float = 0,
    quantity: float = 0,
    description: str = "",
    remark: str = "",
    attendee_count: int = 0,
    guest_info: str = "",
    currency: str = "",
    exchange_rate: float = 0,
) -> dict:
    """修改报销单草稿中【已存在】的一条费用明细（按 item_seq 定位），保留其已关联发票。
    用于纠正金额/子类/说明等，避免"删掉重加"导致丢失已附发票。
    只需传要修改的字段：传了金额(amount 或 unit_price+quantity)才会重算金额；
    不传金额则金额不变。返回更新后的报销单汇总。"""
    from app.core.database import AsyncSessionLocal
    from app.services.expense_sheet_svc import ExpenseSheetService
    from app.core.exceptions import BusinessException, ReimbursementNotFoundError

    c = _ctx()
    async with AsyncSessionLocal() as db:
        svc = ExpenseSheetService(db)
        try:
            reimb0 = await svc.get(reimb_id)
        except ReimbursementNotFoundError:
            return {"success": False, "message": f"未找到报销单 {reimb_id}"}
        if reimb0.user_id != c.get("user_id"):
            return {"success": False, "message": "只能编辑本人的报销单。"}
        try:
            reimb, item = await svc.update_item(
                reimb_id, item_seq, subtype=subtype, amount=amount,
                unit_price=unit_price, quantity=quantity,
                description=description if description else None,
                remark=remark if remark else None,
                attendee_count=attendee_count if attendee_count else None,
                guest_info=guest_info if guest_info else None,
                currency=currency, exchange_rate=exchange_rate,
            )
        except BusinessException as e:
            return {"success": False, "message": e.message}
    return {"success": True, "item_seq": item_seq, "sheet": _fmt_sheet(reimb),
            "message": f"已更新明细#{item_seq}。"}


@tool
async def remove_expense_item(reimb_id: str, item_seq: int) -> dict:
    """从报销单草稿中删除指定序号(seq)的费用明细。"""
    from app.core.database import AsyncSessionLocal
    from app.services.expense_sheet_svc import ExpenseSheetService
    from app.core.exceptions import BusinessException, ReimbursementNotFoundError

    c = _ctx()
    async with AsyncSessionLocal() as db:
        svc = ExpenseSheetService(db)
        try:
            reimb0 = await svc.get(reimb_id)
        except ReimbursementNotFoundError:
            return {"success": False, "message": f"未找到报销单 {reimb_id}"}
        if reimb0.user_id != c.get("user_id"):
            return {"success": False, "message": "只能编辑本人的报销单。"}
        try:
            reimb = await svc.remove_item(reimb_id, item_seq)
        except BusinessException as e:
            return {"success": False, "message": e.message}
    return {"success": True, "sheet": _fmt_sheet(reimb), "message": f"已删除明细#{item_seq}。"}


@tool
async def attach_invoice(
    reimb_id: str, item_seq: int,
    amount: float = 0, invoice_code: str = "", invoice_number: str = "",
    invoice_date: str = "", seller_name: str = "",
) -> dict:
    """为报销单中某条【费用明细行】关联一张发票（用于大额/必须凭票的明细）。
    item_seq 为明细序号；amount 为发票真实金额，【必须提供】且应来自 OCR 识别或发票原件，
    系统不会用明细金额自动代填（金额铁律）。发票金额合计不得超过该明细金额。
    若用户已上传发票文件，请先用 ocr_uploaded_invoices 识别，再用识别到的金额调用本工具。"""
    from app.core.database import AsyncSessionLocal
    from app.services.expense_sheet_svc import ExpenseSheetService
    from app.core.exceptions import BusinessException, ReimbursementNotFoundError

    c = _ctx()
    async with AsyncSessionLocal() as db:
        svc = ExpenseSheetService(db)
        try:
            reimb0 = await svc.get(reimb_id)
        except ReimbursementNotFoundError:
            return {"success": False, "message": f"未找到报销单 {reimb_id}"}
        if reimb0.user_id != c.get("user_id"):
            return {"success": False, "message": "只能编辑本人的报销单。"}
        try:
            reimb = await svc.attach_invoice_to_item(reimb_id, item_seq, {
                "amount": amount, "invoice_code": invoice_code,
                "invoice_number": invoice_number, "invoice_date": invoice_date,
                "seller_name": seller_name,
            })
        except BusinessException as e:
            return {"success": False, "message": e.message}
    return {"success": True, "sheet": _fmt_sheet(reimb), "message": f"已为明细#{item_seq}关联发票。"}


@tool
async def view_reimbursement_draft(reimb_id: str = "") -> dict:
    """查看报销单草稿的当前内容（分类小计、各明细、总额、缺票项）。
    reimb_id 留空时返回当前用户最近一张草稿。用于向用户汇报进度或提交前确认。"""
    from app.core.database import AsyncSessionLocal
    from app.services.expense_sheet_svc import ExpenseSheetService
    from app.core.exceptions import ReimbursementNotFoundError

    c = _ctx()
    async with AsyncSessionLocal() as db:
        svc = ExpenseSheetService(db)
        if not reimb_id:
            reimb = await svc.find_active_draft(c.get("user_id", ""))
            if not reimb:
                return {"success": False, "message": "当前没有进行中的报销单草稿。"}
        else:
            try:
                reimb = await svc.get(reimb_id)
            except ReimbursementNotFoundError:
                return {"success": False, "message": f"未找到报销单 {reimb_id}"}
            if reimb.user_id != c.get("user_id") and c.get("user_role") not in ("admin", "finance"):
                return {"success": False, "message": "无权查看该报销单。"}
        v = svc.validate(reimb)
        sheet = _fmt_sheet(reimb)
    # 构建一目了然的预览汇报（总额 + 分类小计 + 缺票警告）
    warnings = v.get("warnings", [])
    errors = v.get("errors", [])
    preview_parts = [
        f"📋 报销单预览（{sheet['title']}，共 {sheet['item_count']} 条明细）",
        f"总额：¥{sheet['total_amount']:,.2f}  "
        f"（需票: ¥{sheet.get('invoice_amount',0):,.2f}  |  "
        f"补贴: ¥{sheet.get('subsidy_amount',0):,.2f}）",
    ]
    for cat in sheet.get("category_subtotals", []):
        preview_parts.append(f"  {cat['category']}: ¥{cat['amount']:,.2f}")
    if errors:
        preview_parts.append(f"⚠️ 校验未通过 ({len(errors)} 项): " + "; ".join(errors[:3]))
    if warnings:
        preview_parts.append(f"💡 提示 ({len(warnings)} 项): " + "; ".join(warnings[:3]))
    preview_parts.append("")
    preview_parts.append("请将以上预览完整展示给用户，等用户明确确认「可以提交」后，再调用 submit_reimbursement。")
    return {
        "success": True, "sheet": sheet, "validation": v,
        "message": "\n".join(preview_parts),
    }


@tool
async def submit_reimbursement(reimb_id: str = "") -> dict:
    """提交报销单草稿进入审批。提交前会严格校验：
    大额/必须凭票项必须已关联发票，否则拒绝提交并列出缺票明细。
    reimb_id 留空时提交当前用户最近一张草稿。
    提交成功后返回汇总（总额/发票额/补贴额/是否需特殊审批）。"""
    from app.core.database import AsyncSessionLocal
    from app.services.expense_sheet_svc import ExpenseSheetService
    from app.services.pdf_svc import generate_and_store_reimbursement_pdf
    from app.services.reimbursement_svc import ReimbursementService
    from app.core.exceptions import ReimbursementNotFoundError

    c = _ctx()
    if not c.get("user_id"):
        return {"success": False, "message": "您尚未登录，无法提交报销。"}
    async with AsyncSessionLocal() as db:
        svc = ExpenseSheetService(db)
        if not reimb_id:
            reimb = await svc.find_active_draft(c.get("user_id", ""))
            if not reimb:
                return {"success": False, "message": "当前没有可提交的报销单草稿。"}
            reimb_id = reimb.id
        else:
            try:
                reimb = await svc.get(reimb_id)
            except ReimbursementNotFoundError:
                return {"success": False, "message": f"未找到报销单 {reimb_id}"}
            if reimb.user_id != c.get("user_id"):
                return {"success": False, "message": "只能提交本人的报销单。"}
        result = await svc.submit(reimb_id)

    if not result.get("success"):
        return result

    # 生成报销单 PDF（失败不阻断）
    download_url = ""
    try:
        async with AsyncSessionLocal() as db:
            rsvc = ReimbursementService(db)
            reimb2 = await rsvc.get_by_id(reimb_id)
            info = await generate_and_store_reimbursement_pdf(reimb2)
            download_url = info.get("download_url", "")
    except Exception as e:
        logger.warning(f"报销单 PDF 生成失败（不阻断）: {e}")
    result["pdf_download_url"] = download_url
    # 把真实下载地址并入面向用户的 message，避免 LLM 另行编造链接；
    # 无地址时明确告知不要虚构。
    if download_url:
        result["message"] = (result.get("message", "") +
                             f" 报销单 PDF 下载地址：{download_url}（请原样提供给用户，勿改写）。")
    else:
        result["message"] = (result.get("message", "") +
                             " PDF 稍后可在系统「文档中心/进度查询」下载（本次未生成下载地址，请勿编造链接）。")

    # 自动邮件通知：提交成功 → 通知申请人所在部门的部门经理进行一审（同步等待结果，
    # 以便据实告知用户成功/失败；失败时用户可稍后让 agent 重发）。附 PDF、抄送管理员。
    try:
        from app.services.notification_svc import send_reimbursement_notification
        nres = await send_reimbursement_notification(reimb_id, "manager")
        if nres.get("success"):
            result["message"] += f" 已邮件通知部门经理一审（送达 {nres['primary_delivered']} 位）。"
        else:
            result["message"] += (
                f" ⚠️ 一审邮件通知发送失败：{nres.get('reason', '未知原因')}。"
                "报销单已正常提交，您可稍后对我说\"重发一审通知\"，我会再试一次。"
            )
        result["notification"] = nres
    except Exception as e:
        logger.warning(f"提交后通知部门经理异常（不阻断）: {e}")
        result["message"] += " ⚠️ 一审邮件通知发送异常，您可稍后让我重发。"
    return result


# =============================================================================
# 8. 为报销单生成 PDF（支持草稿预览，可反复生成）
# =============================================================================
@tool
async def generate_reimbursement_pdf_doc(reimb_id: str = "") -> dict:
    """生成报销单 PDF。既可用于【草稿预览】，也可用于已提交单据。

    - reimb_id 留空 → 取当前用户【最近一张草稿】，生成【预览版】PDF 供用户查看确认。
      这是"给我生成 PDF 预览"场景的默认用法。
    - 草稿阶段可【反复生成】：用户看后若不满意，先协助其修改明细（add/update/remove_expense_item），
      再调用本工具重新生成预览；用户彻底满意确认后，才调用 submit_reimbursement 提交。
    - 也可传具体 reimb_id 为任意已存在报销单生成 PDF。
    权限：员工仅本人、经理仅本部门。返回的下载地址必须原样提供给用户，绝不改写或编造。"""
    from app.core.database import AsyncSessionLocal
    from app.services.expense_sheet_svc import ExpenseSheetService
    from app.services.pdf_svc import generate_and_store_reimbursement_pdf
    from app.core.exceptions import ReimbursementNotFoundError

    c = _ctx()
    uid, role, dept = c.get("user_id", ""), c.get("user_role", ""), c.get("user_department", "")
    async with AsyncSessionLocal() as db:
        svc = ExpenseSheetService(db)
        if not reimb_id:
            reimb = await svc.find_active_draft(uid)
            if not reimb:
                return {"success": False,
                        "message": "当前没有进行中的报销单草稿可生成 PDF，请先创建并填写草稿。"}
        else:
            try:
                reimb = await svc.get(reimb_id)
            except ReimbursementNotFoundError:
                return {"success": False, "message": f"未找到报销单 {reimb_id}"}
        if role == "employee" and reimb.user_id != uid:
            return {"success": False, "message": "只能为本人的报销单生成 PDF"}
        if role == "manager" and reimb.department != dept:
            return {"success": False, "message": f"只能为本部门（{dept}）的报销单生成 PDF"}
        rid, status = reimb.id, reimb.status
        try:
            info = await generate_and_store_reimbursement_pdf(reimb)
        except Exception as e:
            logger.error(f"生成报销单 PDF 失败: {e}")
            return {"success": False, "message": "报销单 PDF 生成失败，请稍后重试。"}

    _url = info.get("download_url", "")
    is_draft = (status == "draft")
    if is_draft:
        msg = (
            f"已生成【预览版】报销单 PDF（草稿，尚未提交）：{_url}（请原样展示给用户）。"
            "请让用户查看：若满意，再调用 submit_reimbursement 提交；"
            "若需修改，请先协助调整明细后【重新生成预览】。切勿在用户明确确认前提交。"
            if _url else
            "预览版报销单 PDF 已生成，可在系统「文档中心」下载（本次无下载地址，请勿编造链接）。"
        )
    else:
        msg = (
            f"报销单 PDF 已生成，下载地址：{_url}（请原样提供给用户，勿改写或编造）。"
            if _url else
            "报销单 PDF 已生成，可在系统「文档中心」下载（本次无下载地址，请勿编造链接）。"
        )
    return {"success": True, "reimb_id": rid, "is_draft": is_draft,
            "pdf_download_url": _url, "message": msg}


# =============================================================================
# 9. 审批
# =============================================================================
@tool
async def list_pending_approvals() -> dict:
    """列出【当前登录用户本人】待审批的报销单，已按角色与审批阶段自动过滤。

    - 经理：只返回本部门阶段一（部门经理审批）待处理的单；
    - 财务：只返回阶段二（财务审批）待处理的单；
    - 管理员：返回全部待审批的单；
    - 员工：无审批权限，返回空列表。

    用于审批流程第一步——先了解有哪些单需要处理，然后再逐张与用户确认。
    返回每张单的摘要（单号、申请人、部门、金额、当前阶段、摘要）。"""
    from app.core.database import AsyncSessionLocal
    from app.models.reimbursement import Reimbursement
    from app.core.approval_rules import can_role_approve_step
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    c = _ctx()
    uid, role, dept = c.get("user_id", ""), c.get("user_role", ""), c.get("user_department", "")

    if role not in ("manager", "admin", "finance"):
        return {"has_approval_rights": False, "count": 0, "items": [],
                "message": "您没有审批权限（当前角色: employee）。只有部门经理、财务或管理员可审批。"}

    async with AsyncSessionLocal() as db:
        conds = [Reimbursement.status == "pending"]
        if role == "manager":
            conds.append(Reimbursement.department == dept)
        stmt = (
            select(Reimbursement)
            .options(
                selectinload(Reimbursement.approvals),
                selectinload(Reimbursement.items),
            )
            .where(*conds)
            .order_by(Reimbursement.created_at.desc())
        )
        reimbs = (await db.execute(stmt)).scalars().all()

    items = []
    for r in reimbs:
        pending = sorted(
            [a for a in (r.approvals or []) if a.action == "pending"],
            key=lambda a: a.step,
        )
        if not pending:
            continue
        stage_title = pending[0].approver  # "部门经理" or "财务审批"
        if not can_role_approve_step(role, stage_title):
            continue  # wrong stage for this role

        items.append({
            "reimb_id": r.id,
            "user_name": r.user_name,
            "department": r.department,
            "expense_type": r.expense_type,
            "title": r.title or "",
            "total_amount": float(r.total_amount or 0),
            "current_stage": stage_title,
            "item_count": len(r.items or []),
            "created_at": r.created_at.isoformat() if r.created_at else "",
        })

    return {
        "has_approval_rights": True,
        "count": len(items),
        "items": items,
        "message": (
            f"您当前有 {len(items)} 张待审批报销单（角色: {role}，部门: {dept}）"
            if items else
            f"目前没有需要您审批的报销单（角色: {role}，部门: {dept}）"
        ),
    }


@tool
async def approve_reimbursement(reimb_id: str, action: str, comment: str = "") -> dict:
    """对【一张】报销单执行审批操作。
    务必先调用 list_pending_approvals 确认该单在当前用户的待审列表中，
    并且用户已明确表态（通过/驳回/退回）后再调用，绝不未经确认自行审批。
    action: approve(通过)/reject(驳回)/return(退回)。
    comment: 审批意见（驳回时建议询问原因后填入；用户不愿说明时可留空）。
    权限：仅经理(限本部门)、管理员、财务可操作。
    批量审批：对每一张分别调用本工具，不要一次传多张。"""
    from app.core.database import AsyncSessionLocal
    from app.services.reimbursement_svc import ApprovalService
    from app.models.reimbursement import Reimbursement
    from app.core.exceptions import ReimbursementNotFoundError, BusinessException

    c = _ctx()
    uname, role, dept = c.get("user_name", "") or "审批人", c.get("user_role", ""), c.get("user_department", "")
    if role not in ("manager", "admin", "finance"):
        return {"success": False, "message": "您没有审批权限，只有部门经理、财务或管理员可审批。"}
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
            await svc.record(reimb_id, uname, action, comment or None, approver_role=role)
        except (ReimbursementNotFoundError, BusinessException) as e:
            return {"success": False, "message": e.message}
        except Exception as e:
            logger.error(f"审批失败: {e}")
            return {"success": False, "message": "审批操作失败，请稍后重试。"}
        # 记录审批后的最新状态（用于判断是否触发二审通知）
        await db.refresh(reimb)
        new_status = reimb.status

    cn = {"approve": "已通过", "reject": "已驳回", "return": "已退回"}[action]
    extra = ""
    # 一审（部门经理）通过后仍是 pending → 进入二审，同步邮件通知财务（附 PDF、抄送管理员）。
    if action == "approve" and new_status == "pending":
        try:
            from app.services.notification_svc import send_reimbursement_notification
            nres = await send_reimbursement_notification(reimb_id, "finance")
            if nres.get("success"):
                extra = f" 已邮件通知财务二审（送达 {nres['primary_delivered']} 位）。"
            else:
                extra = (
                    f" ⚠️ 二审邮件通知发送失败：{nres.get('reason', '未知原因')}。"
                    "审批已生效，您可稍后对我说\"重发二审通知\"，我会再试一次。"
                )
        except Exception as e:
            logger.warning(f"一审通过后通知财务异常（不阻断）: {e}")
            extra = " ⚠️ 二审邮件通知发送异常，您可稍后让我重发。"
    return {"success": True, "reimb_id": reimb_id, "result": cn,
            "new_status": new_status, "message": f"报销单 {reimb_id} {cn}。{extra}"}


@tool
async def pay_reimbursement(reimb_id: str, comment: str = "") -> dict:
    """出纳付款：把【已通过(approved)】的报销单标记为【已付款(paid)】。
    权限：仅财务/出纳(finance) 或管理员(admin) 可操作。"""
    from app.core.database import AsyncSessionLocal
    from app.services.reimbursement_svc import ApprovalService
    from app.core.exceptions import ReimbursementNotFoundError, BusinessException

    c = _ctx()
    uname, role = c.get("user_name", "") or "出纳", c.get("user_role", "")
    if role not in ("finance", "admin"):
        return {"success": False, "message": "您没有付款权限，只有财务/出纳可付款。"}
    async with AsyncSessionLocal() as db:
        svc = ApprovalService(db)
        try:
            await svc.mark_paid(reimb_id, uname, operator_role=role, comment=comment or None)
        except (ReimbursementNotFoundError, BusinessException) as e:
            return {"success": False, "message": e.message}
        except Exception as e:
            logger.error(f"付款失败: {e}")
            return {"success": False, "message": "付款操作失败，请稍后重试。"}
    return {"success": True, "reimb_id": reimb_id, "result": "已付款", "message": f"报销单 {reimb_id} 已付款。"}


@tool
async def resend_approval_notification(reimb_id: str = "") -> dict:
    """重新发送某报销单【当前待审批阶段】的邮件通知（附 PDF、抄送管理员）。
    当上一次自动通知发送失败时，用户可让你重发。

    reimb_id 留空时，默认取当前用户【本人最近一张待审批的报销单】（适用于申请人重发一审）。
    权限：申请人可重发本人单的一审；本部门经理可重发本部门单的二审；管理员可重发任意。
    仅当报销单处于"待审批(pending)"时可重发。"""
    from app.core.database import AsyncSessionLocal
    from app.services.expense_sheet_svc import ExpenseSheetService
    from app.services.notification_svc import (
        send_reimbursement_notification, infer_current_stage, can_resend,
    )
    from app.core.exceptions import ReimbursementNotFoundError
    from app.models.reimbursement import Reimbursement
    from sqlalchemy import select

    c = _ctx()
    uid, role, dept = c.get("user_id", ""), c.get("user_role", ""), c.get("user_department", "")
    if not uid:
        return {"success": False, "message": "您尚未登录。"}

    async with AsyncSessionLocal() as db:
        svc = ExpenseSheetService(db)
        if not reimb_id:
            # 默认取本人最近一张待审批报销单
            row = (await db.execute(
                select(Reimbursement)
                .where(Reimbursement.user_id == uid, Reimbursement.status == "pending")
                .order_by(Reimbursement.updated_at.desc()).limit(1)
            )).scalar_one_or_none()
            if not row:
                return {"success": False, "message": "未找到需要重发通知的报销单，请提供报销单号。"}
            reimb_id = row.id
        try:
            reimb = await svc.get(reimb_id)
        except ReimbursementNotFoundError:
            return {"success": False, "message": f"未找到报销单 {reimb_id}"}
        if reimb.status != "pending":
            return {"success": False,
                    "message": f"报销单 {reimb_id} 当前状态为「{reimb.status}」，非待审批，无需再发送审批提醒。"}
        stage = infer_current_stage(reimb)
        reimb_user_id, reimb_dept = reimb.user_id, reimb.department

    if not stage:
        return {"success": False, "message": "未找到该报销单当前的待审批阶段。"}
    if not can_resend(stage, role, uid, reimb_user_id, dept, reimb_dept):
        return {"success": False,
                "message": "您无权重发该报销单的审批通知（申请人可重发一审；本部门经理可重发二审；管理员不限）。"}

    nres = await send_reimbursement_notification(reimb_id, stage)
    stage_cn = nres.get("stage_cn", stage)
    if nres.get("success"):
        return {"success": True, "reimb_id": reimb_id, "stage": stage, "notification": nres,
                "message": f"已重新发送{stage_cn}通知，送达主审 {nres['primary_delivered']} 位"
                           + (f"、抄送管理员 {nres['admin_delivered']} 位。" if nres.get('admin_delivered') else "。")}
    return {"success": False, "reimb_id": reimb_id, "stage": stage, "notification": nres,
            "message": f"重发{stage_cn}通知仍未成功：{nres.get('reason', '未知原因')}。"
                       "请核对相关审批人是否已绑定有效邮箱，或稍后再试。"}


AGENT_TOOLS = [
    get_current_user_context,
    get_expense_policy,
    get_department_budget,
    check_expense_compliance,
    query_reimbursements,
    ocr_uploaded_invoices,
    start_reimbursement_draft,
    list_my_drafts,
    add_expense_item,
    update_expense_item,
    remove_expense_item,
    attach_invoice,
    view_reimbursement_draft,
    submit_reimbursement,
    generate_reimbursement_pdf_doc,
    list_pending_approvals,
    approve_reimbursement,
    pay_reimbursement,
    resend_approval_notification,
]
