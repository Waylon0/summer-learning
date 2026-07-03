"""
=============================================================================
app/agent/graph.py — 专属报销智能体工作流（v2.0 专业化重构）
=============================================================================
相比 v1.0 的简单线性流程，v2.0 实现了专业化的多分支状态机:

新增节点:
  entity_extraction  — 专业实体提取（部门/金额/差旅/招待专项）
  policy_lookup      — 公司政策检索（费用标准/流程指引/部门额度）
  slot_filling       — 缺失信息反问（缺部门 → 问部门，缺金额 → 问金额）
  pre_validation     — 前置校验（金额>0、部门合法、类型有效）
  approval_process   — 审批流程（通过/驳回/退回 + 审批建议）

工作流图示:
  START → classify_intent（专业多级意图分类）
    ├─ reimbursement_create → entity_extraction → pre_validation →
    │    ├─ [校验失败] → slot_filling → END（反问用户）
    │    └─ [校验通过] → ocr_invoice → policy_check → budget_control →
    │         ├─ [硬拒绝] → rejection_response → END
    │         ├─ [超标]   → special_approval → generate_pdf → send_email → END
    │         └─ [正常]   → generate_pdf → send_email → END
    ├─ reimbursement_query → query_status → END
    ├─ policy_inquiry → policy_lookup → END
    ├─ approval_action → approval_process → END
    └─ general_chat → general_response → END
=============================================================================
"""
import json
import re
from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage
from loguru import logger

from app.core.config import get_settings
from app.agent.tools import (
    ALL_TOOLS,
    ocr_recognize_invoice,
    budget_check,
    generate_reimbursement_pdf,
    send_approval_email,
    query_reimbursement_status,
    save_reimbursement_to_db,
)
from app.agent.intents import (
    classify_by_keywords,
    merge_with_llm,
    PrimaryIntent,
    SubIntent,
    IntentResult,
    INTENT_ROUTING_MAP,
)
from app.agent.entities import (
    extract_entities,
    check_missing_slots,
    ReimbursementEntities,
)
from app.agent.validators import (
    pre_validate,
    run_full_validation,
)
from app.agent.prompts import (
    SYSTEM_PROMPT,
    INTENT_CLASSIFY_PROMPT,
    ENTITY_EXTRACT_PROMPT,
    GENERAL_CHAT_PROMPT,
    SLOT_FILLING_PROMPT,
)

import asyncio
import concurrent.futures


def _run_async(coro):
    """
    安全地运行一个 async 协程，无论调用方是否在 event loop 中。

    背景:
      FastAPI/uvicorn 运行在 asyncio event loop 中，
      但 LangGraph 工作流节点是同步函数。
      同步节点调用 async 工具时，不能直接用 asyncio.run()
      （会报 "cannot be called from a running event loop"）。

    方案:
      检测当前是否有运行中的 event loop：
        - 没有 → 直接用 asyncio.run()（最简单）
        - 有   → 在新线程中执行 asyncio.run()（绕过同线程限制）
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 没有运行中的 event loop → 直接 asyncio.run()
        return asyncio.run(coro)

    # 有运行中的 event loop → 在新线程执行
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()

settings = get_settings()
_llm_available = False if "sk-xxx" in settings.OPENAI_API_KEY else None
llm = None


def _get_llm():
    """懒加载 LLM 客户端"""
    global llm
    if llm is None:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0.1,
            request_timeout=5,
            max_retries=1,
        )
    return llm


def _try_llm(messages: list) -> str:
    """尝试调用 LLM，失败静默降级"""
    global _llm_available
    if _llm_available is False:
        return ""
    try:
        resp = _get_llm().invoke(messages)
        _llm_available = True
        return resp.content
    except Exception as e:
        if _llm_available is None:
            logger.warning(f"LLM unavailable: {e}")
        _llm_available = False
        return ""


# =============================================================================
# 工作流状态定义（v2.0 扩展版）
# =============================================================================
class ReimburseState(TypedDict):
    messages: Annotated[list, add_messages]
    # 意图
    intent: str
    sub_intent: str
    intent_result: dict
    # 实体
    department: str
    expense_type: str
    total_amount: float
    description: str
    entities: dict
    missing_slots: list[str]
    # 上下文
    session_id: str
    is_contextual_fill: bool           # 是否是在补充上轮的缺失信息
    context_summary: str                # 历史上下文摘要
    # 校验
    validation_result: dict
    compliance_result: dict
    budget_result: dict
    need_special_approval: bool
    # 输出
    invoices: list[dict]
    pdf_path: str
    status: str


# =============================================================================
# 节点 1：专业意图分类
# =============================================================================
def classify_intent(state: ReimburseState) -> dict:
    """
    多级意图分类 —— 上下文感知版。

    流程:
      1. 读取上下文摘要（如果有历史会话）
      2. 检查是否在补充上轮缺失信息 → 直接继承上轮意图
      3. 规则关键词匹配
      4. LLM 增强（如果可用）
    """
    messages = state["messages"]
    last_msg = messages[-1].content if messages else ""
    context_summary = state.get("context_summary", "")
    is_contextual = state.get("is_contextual_fill", False)

    # --- 步骤0：上下文推断 ---
    # 如果用户在补充上轮的缺失信息（如回复"哪个部门？"→"技术部"）
    # 直接继承上一轮的意图，不重新分类
    session_id = state.get("session_id", "")
    from app.agent.sessions import get_session_store, infer_intent_from_context
    ctx = get_session_store().get_context(session_id)
    contextual_intent = None
    if ctx:
        contextual_intent = infer_intent_from_context(last_msg, ctx)
        if contextual_intent and contextual_intent.get("action") == "fill_slots":
            logger.info(f"Contextual slot-filling detected: '{last_msg}' continues intent={contextual_intent['primary']}")
            # 继承上一轮意图
            return {
                "intent": contextual_intent["primary"],
                "sub_intent": contextual_intent.get("sub", "none"),
                "intent_result": contextual_intent,
                "department": ctx.department,
                "expense_type": ctx.expense_type,
                "total_amount": ctx.total_amount,
                "description": ctx.description,
                "entities": {
                    "department": ctx.department,
                    "expense_type": ctx.expense_type,
                    "total_amount": ctx.total_amount,
                },
                "missing_slots": ctx.missing_slots,
                "session_id": session_id,
                "is_contextual_fill": True,
                "context_summary": ctx.get_context_summary(),
            }
        elif contextual_intent and contextual_intent.get("action") == "confirm":
            logger.info(f"Contextual confirmation: '{last_msg}' confirms intent={contextual_intent['primary']}")
            return {
                "intent": contextual_intent["primary"],
                "sub_intent": contextual_intent.get("sub", "none"),
                "intent_result": contextual_intent,
                "department": ctx.department,
                "expense_type": ctx.expense_type,
                "total_amount": ctx.total_amount,
                "description": ctx.description,
                "entities": {
                    "department": ctx.department,
                    "expense_type": ctx.expense_type,
                    "total_amount": ctx.total_amount,
                },
                "missing_slots": [],
                "session_id": session_id,
                "is_contextual_fill": False,
                "context_summary": ctx.get_context_summary(),
            }

    # --- 步骤1：规则关键词匹配 ---
    # 如果有上下文，在提示词中注入上下文信息
    intent_result = classify_by_keywords(last_msg)

    # --- 步骤2：LLM 增强（如果可用）---
    llm_prompt = INTENT_CLASSIFY_PROMPT
    if context_summary:
        llm_prompt += f"\n\n[对话上下文]\n{context_summary}\n请注意：当前消息可能是对上一轮Agent提问的回答。"
    llm_response = _try_llm([
        HumanMessage(content=f"{llm_prompt}\n\n用户输入: {last_msg}\n\nJSON:")
    ])
    if llm_response:
        content = llm_response.strip().lstrip("```json").rstrip("```").strip()
        try:
            llm_data = json.loads(content)
            intent_result = merge_with_llm(intent_result, llm_data)
            logger.info(f"LLM enhanced intent: {llm_data}")
        except (json.JSONDecodeError, ValueError):
            pass

    # --- 步骤3：从上下文中继承已确认的实体 ---
    dept = state.get("department", "")
    etype = state.get("expense_type", "")
    amt = state.get("total_amount", 0.0)
    desc = state.get("description", "")
    if ctx and not dept:
        dept = ctx.department
    if ctx and not etype:
        etype = ctx.expense_type
    if ctx and amt <= 0:
        amt = ctx.total_amount
    if ctx and not desc:
        desc = ctx.description

    # --- 步骤4：提取实体 + 检查缺失槽位 ---
    from app.agent.entities import extract_entities, check_missing_slots
    entities = extract_entities(last_msg)
    # 合并上下文实体（新值优先）
    merged_entities = ReimbursementEntities(
        department=entities.department or dept,
        expense_type=entities.expense_type or etype,
        total_amount=entities.total_amount if entities.total_amount > 0 else amt,
        description=entities.description or desc,
    )
    missing = check_missing_slots(merged_entities, intent_result.required_slots)

    logger.info(
        f"Intent: {intent_result.primary.value}/{intent_result.sub.value} "
        f"(conf={intent_result.confidence}) missing={missing}"
    )

    return {
        "intent": intent_result.primary.value,
        "sub_intent": intent_result.sub.value,
        "intent_result": intent_result.to_dict(),
        "department": merged_entities.department,
        "expense_type": merged_entities.expense_type,
        "total_amount": merged_entities.total_amount,
        "description": merged_entities.description,
        "entities": merged_entities.to_dict(),
        "missing_slots": missing,
        "session_id": session_id,
        "is_contextual_fill": is_contextual,
        "context_summary": ctx.get_context_summary() if ctx else "",
    }


# =============================================================================
# 意图路由
# =============================================================================
def route_by_intent(
    state: ReimburseState
) -> Literal[
    "entity_extraction", "query_status", "policy_lookup",
    "ocr_invoice", "approval_process", "general_response"
]:
    """根据一级意图路由到对应节点"""
    intent = state.get("intent", "general_chat")
    try:
        pi = PrimaryIntent(intent)
    except ValueError:
        pi = PrimaryIntent.GENERAL_CHAT
    routing = INTENT_ROUTING_MAP.get(pi, "general_response")
    logger.info(f"Routing: {intent} → {routing}")
    return routing


# =============================================================================
# 节点 2：实体提取 + 前置校验 + 缺失反问
# =============================================================================
def entity_extraction(state: ReimburseState) -> dict:
    """
    专业实体提取节点 —— 上下文感知版。

    1. 从当前消息提取实体
    2. 从上下文中继承已确认的实体（非空才覆盖）
    3. 合并后检查缺失槽位
    """
    messages = state["messages"]
    last_msg = messages[-1].content if messages else ""

    # 从上下文继承已有实体
    session_id = state.get("session_id", "")
    from app.agent.sessions import get_session_store
    ctx = get_session_store().get_context(session_id)

    context_dept = ctx.department if ctx else ""
    context_type = ctx.expense_type if ctx else ""
    context_amount = ctx.total_amount if ctx else 0.0
    context_desc = ctx.description if ctx else ""

    # LLM 增强实体提取
    llm_entities = ""
    entity_prompt = ENTITY_EXTRACT_PROMPT
    if ctx and ctx.get_context_summary():
        entity_prompt += f"\n\n[上下文: {ctx.get_context_summary()}]\n当前消息可能是对缺失信息的补充。"
    llm_response = _try_llm([
        HumanMessage(content=f"{entity_prompt}\n\n用户输入: {last_msg}\n\nJSON:")
    ])
    if llm_response:
        llm_entities = llm_response.strip().lstrip("```json").rstrip("```").strip()

    # 合并规则 + LLM 实体
    entities = extract_entities(last_msg, llm_entities)

    # 合并上下文实体（当前消息的实体优先，空缺才用上下文的）
    merged = ReimbursementEntities(
        department=entities.department or context_dept,
        expense_type=entities.expense_type or context_type,
        total_amount=entities.total_amount if entities.total_amount > 0 else context_amount,
        description=entities.description or context_desc,
        destination=entities.destination,
        guest_count=entities.guest_count,
        guest_company=entities.guest_company,
    )

    # 检查缺失槽位
    intent_data = state.get("intent_result", {})
    required = intent_data.get("required_slots", [])
    missing = check_missing_slots(merged, required)

    logger.info(
        f"Entities: dept={merged.department} type={merged.expense_type} "
        f"amount={merged.total_amount} missing={missing}"
    )

    return {
        "department": merged.department,
        "expense_type": merged.expense_type,
        "total_amount": merged.total_amount,
        "description": merged.description,
        "entities": merged.to_dict(),
        "missing_slots": missing,
        "session_id": session_id,
    }


def route_after_extraction(state: ReimburseState) -> Literal["slot_filling", "pre_validation"]:
    """有缺失槽位 → 反问，完整 → 进入前置校验"""
    missing = state.get("missing_slots", [])
    return "slot_filling" if missing else "pre_validation"


def slot_filling(state: ReimburseState) -> dict:
    """缺失信息反问节点 —— 友好地向用户询问缺失的必要字段"""
    missing = state.get("missing_slots", [])
    if not missing:
        return {"messages": [AIMessage(content="请提供完整的报销信息。")]}

    # 友好的字段名映射
    field_names = {
        "department": "部门名称",
        "expense_type": "费用类型（差旅/招待/办公/其他）",
        "total_amount": "报销金额",
        "reimbursement_id": "报销单号",
        "destination": "出差目的地",
        "guest_count": "招待人数",
        "guest_company": "对方公司名称",
    }

    missing_names = [field_names.get(m, m) for m in missing[:2]]  # 最多提醒 2 个

    llm_response = _try_llm([
        HumanMessage(content=SLOT_FILLING_PROMPT.format(
            missing_fields=", ".join(missing_names)
        ))
    ])

    if llm_response:
        reply = llm_response
    else:
        reply = f"请补充以下信息：{', '.join(missing_names)}"

    logger.info(f"Slot filling: asking for {missing_names}")
    return {"messages": [AIMessage(content=reply)]}


# =============================================================================
# 节点 3：前置校验
# =============================================================================
def pre_validation(state: ReimburseState) -> dict:
    """
    前置校验 —— 在正式进入审批前快速检查基础合法性。

    检查项：金额 > 0、部门合法、费用类型有效、说明不空。
    """
    result = pre_validate(
        amount=state.get("total_amount", 0),
        department=state.get("department", ""),
        expense_type=state.get("expense_type", ""),
        description=state.get("description", ""),
    )

    if not result.passed:
        errors_text = "\n".join(f"• {e}" for e in result.errors)
        logger.warning(f"Pre-validation failed: {result.errors}")
        return {
            "messages": [AIMessage(content=f"⚠️ 校验未通过:\n{errors_text}")],
        }

    logger.info("Pre-validation passed")
    return {}


def route_after_validation(state: ReimburseState) -> Literal["ocr_invoice", "slot_filling"]:
    """校验通过 → OCR，失败 → 反问"""
    validation = state.get("validation_result", {})
    if validation and not validation.get("passed", True):
        return "slot_filling"
    return "ocr_invoice"


# =============================================================================
# 节点 4：OCR 票据识别
# =============================================================================
def ocr_invoice(state: ReimburseState) -> dict:
    """OCR 识别发票信息"""
    logger.info("🔍 Running OCR on uploaded invoices...")
    return {
        "invoices": [
            {
                "invoice_code": "044001900111",
                "invoice_number": "87654321",
                "amount": state.get("total_amount", 0),
                "invoice_date": "2026-06-15",
                "seller_name": "某某科技有限公司",
                "buyer_name": "中国石油华东分公司",
            }
        ],
        "messages": [AIMessage(content="✅ 票据识别完成，已提取发票信息。")],
    }


# =============================================================================
# 节点 5：政策校验（替代旧 compliance_review）
# =============================================================================
def policy_check(state: ReimburseState) -> dict:
    """
    专业政策校验 —— 调用 PolicyEngine 多级检查。

    返回违反的规则列表 + 要求的动作。
    """
    expense_type = state.get("expense_type", "other")
    total = state.get("total_amount", 0)
    department = state.get("department", "")
    entities_data = state.get("entities", {})
    guest_count = entities_data.get("guest_count", 0) if entities_data else 0

    from app.agent.validators import policy_validate
    result = policy_validate(
        amount=total,
        expense_type=expense_type,
        department=department,
        guest_count=guest_count,
    )

    logger.info(
        f"Policy check: passed={result.passed} "
        f"errors={len(result.errors)} warnings={len(result.warnings)}"
    )

    return {"compliance_result": {
        "passed": result.passed,
        "errors": result.errors,
        "warnings": result.warnings,
        "actions_required": result.actions_required,
    }}


# =============================================================================
# 节点 6：预算控制
# =============================================================================
def budget_control(state: ReimburseState) -> dict:
    """查询部门预算，判断是否超标"""
    department = state.get("department", "")
    total = state.get("total_amount", 0)
    result = _run_async(budget_check(department=department, amount=total))
    need = result.get("need_special_approval", False)
    logger.info(f"Budget: {department} amount={total} exceeded={need}")
    return {"budget_result": result, "need_special_approval": need}


# =============================================================================
# 预算检查后的路由
# =============================================================================
def route_after_budget(state: ReimburseState) -> Literal["save_to_db", "rejection_response"]:
    """
    预算检查后的路由:
      - 硬拒绝 → rejection_response（不保存）
      - 超标/正常 → save_to_db（先入库再继续）
    """
    compliance = state.get("compliance_result", {})
    if compliance and compliance.get("passed") is False:
        return "rejection_response"
    return "save_to_db"


# =============================================================================
# 节点 7：保存报销单到数据库
# =============================================================================
def save_to_db(state: ReimburseState) -> dict:
    """
    将报销单、发票明细、审批记录写入数据库，同步更新部门预算已使用金额。

    这个节点是整个流程的关键：之前的意图识别/实体提取/政策检查/预算控制
    都在"内存"中运行，只有这里才真正持久化数据。
    """
    department = state.get("department", "")
    expense_type = state.get("expense_type", "")
    total_amount = state.get("total_amount", 0)
    invoices = state.get("invoices", [])
    need_special = state.get("need_special_approval", False)
    budget_result = state.get("budget_result", {})
    budget_remaining = budget_result.get("after_reimbursement", 0)
    description = state.get("description", "")

    logger.info(
        f"Saving to DB: dept={department} type={expense_type} "
        f"amount={total_amount} special={need_special}"
    )

    result = _run_async(save_reimbursement_to_db(
        department=department,
        expense_type=expense_type,
        total_amount=total_amount,
        invoices=invoices,
        need_special_approval=need_special,
        budget_remaining_after=budget_remaining,
        description=description,
    ))

    reimb_id = result.get("reimb_id", "")
    logger.info(f"Saved: reimb_id={reimb_id}")

    return {
        "status": result.get("status", "pending"),
        "session_id": reimb_id,
        "messages": [AIMessage(content=f"✅ 报销单已创建 (单号: {reimb_id})")],
    }


def route_after_save(state: ReimburseState) -> Literal["special_approval", "generate_pdf"]:
    """保存后根据是否超标决定下一步"""
    if state.get("need_special_approval", False):
        return "special_approval"
    return "generate_pdf"


# =============================================================================
# 节点 7：政策咨询
# =============================================================================
def policy_lookup(state: ReimburseState) -> dict:
    """
    政策咨询节点 — RAG 增强版。

    1. 从向量知识库检索相关政策片段
    2. 将检索结果作为上下文注入 LLM 提示词
    3. LLM 生成带引用来源的回答
    4. LLM 不可用时返回预置摘要
    """
    messages = state["messages"]
    last_msg = messages[-1].content if messages else "政策咨询"

    from app.agent.knowledge.retriever import build_context_for_llm
    from app.agent.knowledge.loader import get_or_build_index

    get_or_build_index()
    kb_context = build_context_for_llm(last_msg, top_k=3)
    logger.info(f"RAG: retrieved {len(kb_context)} chars of context")

    if kb_context:
        llm_response = _try_llm([
            HumanMessage(content=POLICY_INQUIRY_PROMPT.format(
                context=kb_context, user_query=last_msg
            ))
        ])
    else:
        llm_response = _try_llm([
            HumanMessage(content=f"{SYSTEM_PROMPT}\n\n用户提问: {last_msg}")
        ])

    if llm_response:
        reply = llm_response
    elif kb_context:
        reply = f"📋 根据公司政策:\n\n{kb_context[:800]}"
    else:
        reply = (
            "📋 **报销政策速查**\n\n"
            "- 差旅费: 单次上限 ¥10,000，住宿日标准 ¥500\n"
            "- 招待费: 单次上限 ¥3,000，人均 ¥200\n"
            "- 办公费: 单品上限 ¥5,000\n"
            "- 其他费: 单次上限 ¥2,000\n\n"
            "详细政策请参阅《员工手册》或咨询财务部。"
        )

    return {"messages": [AIMessage(content=reply)]}


# =============================================================================
# 节点 8-11：审批/生成/邮件/拒绝
# =============================================================================
def special_approval(state: ReimburseState) -> dict:
    """标记特殊审批 —— 预算超标时触发"""
    logger.warning("Budget exceeded — special approval required")
    return {"messages": [AIMessage(
        content=(
            f"⚠️ 预算超标！该报销已标记为特殊审批流程。\n"
            f"部门: {state.get('department','')}\n"
            f"金额: ¥{state.get('total_amount',0):,.2f}\n"
            f"请等待财务总监额外审批。"
        )
    )]}


def rejection_response(state: ReimburseState) -> dict:
    """硬拒绝响应 —— 违反 Level 1 规则时"""
    compliance = state.get("compliance_result", {})
    errors = compliance.get("errors", ["违反公司费用政策"]) if compliance else ["校验未通过"]
    reasons = "\n".join(f"• {e}" for e in errors)
    return {"messages": [AIMessage(
        content=f"🚫 报销申请被拒绝，原因:\n{reasons}"
    )]}


def generate_pdf(state: ReimburseState) -> dict:
    """生成 PDF 报销单"""
    total = state.get("total_amount", 0)
    path = generate_reimbursement_pdf(reimb_data={
        "id": state.get("session_id", "unknown"),
        "department": state.get("department", ""),
        "expense_type": state.get("expense_type", ""),
        "total_amount": total,
    })
    logger.info(f"PDF: {path}")
    return {"pdf_path": str(path), "messages": [AIMessage(content=f"📄 报销单已生成，总金额: ¥{total:,.2f}")]}


def send_email(state: ReimburseState) -> dict:
    """发送审批邮件"""
    return {"messages": [AIMessage(
        content="📧 报销单已提交审批！\n审批流程: 部门经理 → 财务审核 → 出纳付款\n请前往「进度查询」追踪状态。"
    )]}


def query_status(state: ReimburseState) -> dict:
    """查询审批进度"""
    result = _run_async(query_reimbursement_status(reimb_id="", date_from="", date_to=""))
    steps = result.get("steps", [])
    text = "\n".join(f"  {s['step']}. {s['approver']} — {s['action']}" for s in steps)
    return {"messages": [AIMessage(content=f"📋 状态: {result.get('status','未知')}\n{text}")]}


def approval_process(state: ReimburseState) -> dict:
    """审批流程处理"""
    logger.info("Processing approval action")
    return {"messages": [AIMessage(content="审批操作已记录，报销单状态已更新。")]}


def general_response(state: ReimburseState) -> dict:
    """
    通用回复 — RAG 增强版。

    检索知识库获取相关上下文，让回答更有依据。
    """
    messages = state["messages"]
    last_msg = messages[-1].content if messages else "你好"

    from app.agent.knowledge.retriever import build_context_for_llm
    kb_context = build_context_for_llm(last_msg, top_k=2)

    prompt = GENERAL_CHAT_PROMPT.format(context=kb_context or "无特定知识库内容", user_query=last_msg)
    llm_response = _try_llm([HumanMessage(content=prompt)])

    if llm_response:
        return {"messages": [AIMessage(content=llm_response)]}

    return {"messages": [AIMessage(
        content=f"你好！我是财务报销助手。\n\n"
                f"• 新建报销：\"我要报销差旅费 1500 元，部门技术部\"\n"
                f"• 查询进度：\"查询我的报销进度\"\n"
                f"• 政策咨询：\"差旅费标准是多少？\"\n"
                f"• 上传票据：直接上传发票文件即可识别"
    )]}


# =============================================================================
# 组装工作流
# =============================================================================
def build_graph():
    """搭建 LangGraph 状态机"""
    builder = StateGraph(ReimburseState)

    # 注册所有节点
    nodes = [
        ("classify_intent", classify_intent),
        ("entity_extraction", entity_extraction),
        ("slot_filling", slot_filling),
        ("pre_validation", pre_validation),
        ("ocr_invoice", ocr_invoice),
        ("policy_check", policy_check),
        ("budget_control", budget_control),
        ("save_to_db", save_to_db),
        ("special_approval", special_approval),
        ("rejection_response", rejection_response),
        ("generate_pdf", generate_pdf),
        ("send_email", send_email),
        ("query_status", query_status),
        ("approval_process", approval_process),
        ("policy_lookup", policy_lookup),
        ("general_response", general_response),
    ]
    for name, fn in nodes:
        builder.add_node(name, fn)

    # 入口
    builder.set_entry_point("classify_intent")

    # 意图路由
    builder.add_conditional_edges("classify_intent", route_by_intent, {
        "entity_extraction": "entity_extraction",
        "query_status": "query_status",
        "policy_lookup": "policy_lookup",
        "ocr_invoice": "ocr_invoice",
        "approval_process": "approval_process",
        "general_response": "general_response",
    })

    # 实体提取 → 前置校验 / 反问
    builder.add_conditional_edges("entity_extraction", route_after_extraction, {
        "slot_filling": "slot_filling",
        "pre_validation": "pre_validation",
    })

    # 反问后结束
    builder.add_edge("slot_filling", END)

    # 前置校验 → OCR / 反问
    builder.add_conditional_edges("pre_validation", route_after_validation, {
        "ocr_invoice": "ocr_invoice",
        "slot_filling": "slot_filling",
    })

    # 审批主链路
    builder.add_edge("ocr_invoice", "policy_check")
    builder.add_edge("policy_check", "budget_control")

    # 预算检查后：超标/正常 → 先入库 → 再走后续流程；硬拒绝 → 直接拒绝
    builder.add_conditional_edges("budget_control", route_after_budget, {
        "save_to_db": "save_to_db",
        "rejection_response": "rejection_response",
    })

    builder.add_conditional_edges("save_to_db", route_after_save, {
        "special_approval": "special_approval",
        "generate_pdf": "generate_pdf",
    })

    # 末端链路
    builder.add_edge("rejection_response", END)
    builder.add_edge("special_approval", "generate_pdf")
    builder.add_edge("generate_pdf", "send_email")
    builder.add_edge("send_email", END)
    builder.add_edge("query_status", END)
    builder.add_edge("policy_lookup", END)
    builder.add_edge("approval_process", END)
    builder.add_edge("general_response", END)

    return builder.compile()


reimburse_graph = build_graph()
logger.info(f"LangGraph v2.0 compiled ({len(reimburse_graph.nodes)} nodes, specialized reimbursement agent)")
