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
    query_reimbursement_list,
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
    POLICY_INQUIRY_PROMPT,
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
    """尝试调用 LLM，失败静默降级（同步版）"""
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


async def _try_llm_async(messages: list) -> str:
    """尝试调用 LLM，失败静默降级（异步版）"""
    global _llm_available
    if _llm_available is False:
        return ""
    try:
        resp = await _get_llm().ainvoke(messages)
        _llm_available = True
        return resp.content
    except Exception as e:
        if _llm_available is None:
            logger.warning(f"LLM unavailable: {e}")
        _llm_available = False
        return ""


async def _try_llm_structured(messages: list, output_schema: type) -> dict | None:
    """Try LLM with Pydantic structured output, fallback on failure"""
    global _llm_available
    if _llm_available is False:
        return None
    try:
        from langchain_openai import ChatOpenAI
        structured_llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0,
            request_timeout=10,
            max_retries=1,
        ).with_structured_output(output_schema, method="json_mode")
        resp = await structured_llm.ainvoke(messages)
        _llm_available = True
        if isinstance(resp, dict):
            return resp
        if hasattr(resp, "model_dump"):
            return resp.model_dump()
        return resp
    except Exception as e:
        if _llm_available is None:
            logger.warning(f"LLM structured unavailable: {e}")
        _llm_available = False
        return None


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
    reimb_id: str
    attachments: list[str]


# =============================================================================
# 节点 1：专业意图分类
# =============================================================================
async def classify_intent(state: ReimburseState) -> dict:
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

    # --- 步骤2：LLM 增强（优先使用 structured output，降级到 JSON 解析）---
    from pydantic import BaseModel, Field
    class IntentOutput(BaseModel):
        primary: str = Field(description="一级意图")
        sub: str = Field(description="二级意图")
        confidence: float = Field(description="置信度 0-1")

    structured = await _try_llm_structured(
        [HumanMessage(content=f"{INTENT_CLASSIFY_PROMPT}\n\n用户输入: {last_msg}")],
        IntentOutput,
    )
    if structured:
        intent_result = merge_with_llm(intent_result, structured)
        logger.info(f"LLM structured intent: {structured}")
    else:
        llm_response = await _try_llm_async([
            HumanMessage(content=f"{INTENT_CLASSIFY_PROMPT}\n\n用户输入: {last_msg}\n\nJSON:")
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
async def entity_extraction(state: ReimburseState) -> dict:
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
    llm_response = await _try_llm_async([
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


async def slot_filling(state: ReimburseState) -> dict:
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

    llm_response = await _try_llm_async([
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
    失败时使用结构化异常日志。
    """
    from app.core.exceptions import BusinessException, BudgetExceededError
    amount = state.get("total_amount", 0)
    department = state.get("department", "")
    expense_type = state.get("expense_type", "")
    description = state.get("description", "")

    result = pre_validate(
        amount=amount,
        department=department,
        expense_type=expense_type,
        description=description,
    )

    if not result.passed:
        errors_text = "\n".join(f"• {e}" for e in result.errors)
        logger.warning(BusinessException(
            message=f"前置校验未通过: {result.errors}",
            error_code="VALIDATION_FAILED",
        ).message)
        return {
            "messages": [AIMessage(content=f"⚠️ 校验未通过:\n{errors_text}")],
        }

    if amount > 90000:
        logger.warning(
            BudgetExceededError(department=department, amount=amount, remaining=0).message
        )

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
async def ocr_invoice(state: ReimburseState) -> dict:
    """OCR 识别上传的发票文件，支持多张发票分别识别并汇总金额"""
    attachments = state.get("attachments") or []
    if not attachments:
        logger.info("🔍 No attachments — using user-provided amount")
        invoices = [{
            "invoice_code": "",
            "invoice_number": "",
            "amount": state.get("total_amount", 0),
            "invoice_date": "",
            "seller_name": "",
            "buyer_name": "",
        }]
        return {
            "invoices": invoices,
            "messages": [AIMessage(content="ℹ️ 未检测到上传票据，将按您提供的金额提交。")],
        }

    logger.info(f"🔍 OCR processing {len(attachments)} attachment(s)...")
    invoices = []
    total_ocr = 0.0

    for file_path in attachments:
        try:
            result = await ocr_recognize_invoice(file_path)
            if result.get("amount", 0) > 0:
                invoices.append(result)
                total_ocr += result["amount"]
        except Exception as e:
            logger.warning(f"OCR failed for {file_path}: {e}")

    if not invoices:
        invoices = [{
            "invoice_code": "", "invoice_number": "",
            "amount": state.get("total_amount", 0),
            "invoice_date": "", "seller_name": "", "buyer_name": "",
        }]
    else:
        logger.info(f"OCR complete: {len(invoices)} invoice(s), total=¥{total_ocr:,.2f}")

    return {
        "invoices": invoices,
        "messages": [AIMessage(
            content=f"✅ 票据识别完成，共 {len(invoices)} 张发票"
            + (f"，合计 ¥{total_ocr:,.2f}" if total_ocr > 0 else "")
        )],
    }


# =============================================================================
# 节点 5：政策校验（替代旧 compliance_review）
# =============================================================================
def policy_check(state: ReimburseState) -> dict:
    """
    专业政策校验 —— 调用 PolicyEngine 多级检查。
    """
    expense_type = state.get("expense_type") or "other"
    total = state.get("total_amount") or 0
    department = state.get("department") or ""
    entities_data = state.get("entities") or {}
    guest_count = (entities_data or {}).get("guest_count", 0)

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
async def budget_control(state: ReimburseState) -> dict:
    """查询部门预算，判断是否超标"""
    department = state.get("department") or ""
    total = state.get("total_amount") or 0
    result = await budget_check(department=department, amount=total)
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
    compliance = state.get("compliance_result") or {}
    if compliance and compliance.get("passed") is False:
        return "rejection_response"
    return "save_to_db"


# =============================================================================
# 节点 7：保存报销单到数据库
# =============================================================================
async def save_to_db(state: ReimburseState) -> dict:
    """
    将报销单、发票明细、审批记录写入数据库，同步更新部门预算已使用金额。

    这个节点是整个流程的关键：之前的意图识别/实体提取/政策检查/预算控制
    都在"内存"中运行，只有这里才真正持久化数据。
    """
    department = state.get("department") or ""
    expense_type = state.get("expense_type") or ""
    total_amount = state.get("total_amount") or 0
    invoices = state.get("invoices") or []
    need_special = state.get("need_special_approval") or False
    budget_result = state.get("budget_result") or {}
    budget_remaining = (budget_result or {}).get("after_reimbursement", 0)
    description = state.get("description") or ""

    logger.info(
        f"Saving to DB: dept={department} type={expense_type} "
        f"amount={total_amount} special={need_special}"
    )

    result = await save_reimbursement_to_db(
        department=department,
        expense_type=expense_type,
        total_amount=total_amount,
        invoices=invoices,
        need_special_approval=need_special,
        budget_remaining_after=budget_remaining,
        description=description,
    )

    reimb_id = result.get("reimb_id", "")
    logger.info(f"Saved: reimb_id={reimb_id}")

    return {
        "status": result.get("status", "pending"),
        "reimb_id": reimb_id,
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
async def policy_lookup(state: ReimburseState) -> dict:
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
    has_kb = bool(kb_context and len(kb_context) > 20)
    logger.info(f"RAG: {'hit' if has_kb else 'miss'} — {len(kb_context)} chars")

    if has_kb:
        reply = await _try_llm_async([
            HumanMessage(content=POLICY_INQUIRY_PROMPT.format(
                context=kb_context, user_query=last_msg
            ))
        ])
        if reply:
            return {"messages": [AIMessage(content=reply)]}
        return {"messages": [AIMessage(content=f"📋 根据公司政策:\n\n{kb_context[:800]}")]}

    # RAG 未命中 → 切换闲聊模式，LLM 自由对话
    casual_prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"知识库中没有找到与该问题直接相关的政策条款。"
        f"请以友好、专业的态度回答用户问题。如果是闲聊或通用问题，直接自然回复；"
        f"如果涉及报销政策，诚实告知建议咨询财务部。"
    )
    reply = await _try_llm_async([HumanMessage(content=f"{casual_prompt}\n\n用户提问: {last_msg}")])
    if reply:
        return {"messages": [AIMessage(content=reply)]}

    return {"messages": [AIMessage(
        content=(
            f"抱歉，我在知识库中暂未找到与「{last_msg[:30]}」相关的政策。\n\n"
            "如需了解费用标准，可输入：差旅费标准 / 招待费标准 / 办公费标准\n"
            "或直接咨询财务部获取最新政策。"
        )
    )]}


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
    from app.core.exceptions import ComplianceViolationError
    compliance = state.get("compliance_result") or {}
    errors = compliance.get("errors", ["违反公司费用政策"]) if compliance else ["校验未通过"]
    reasons = "\n".join(f"• {e}" for e in errors)
    total = state.get("total_amount", 0)
    etype = state.get("expense_type", "other")
    logger.error(
        ComplianceViolationError(expense_type=etype, amount=total, limit=50000).message
    )
    return {"messages": [AIMessage(
        content=f"🚫 报销申请被拒绝，原因:\n{reasons}"
    )]}


async def generate_pdf(state: ReimburseState) -> dict:
    """生成 PDF 报销单（CPU 密集型任务放线程池，不阻塞事件循环）"""
    import asyncio
    total = state.get("total_amount", 0)
    invoices = state.get("invoices") or []

    path = await asyncio.to_thread(
        generate_reimbursement_pdf,
        reimb_data={
            "id": state.get("reimb_id", state.get("session_id", "unknown")),
            "department": state.get("department", ""),
            "expense_type": state.get("expense_type", ""),
            "total_amount": total,
            "invoices": invoices,
        },
    )
    logger.info(f"PDF: {path}")
    return {"pdf_path": str(path), "messages": [AIMessage(content=f"📄 报销单已生成，总金额: ¥{total:,.2f}")]}


async def send_email(state: ReimburseState) -> dict:
    """发送审批邮件"""
    reimb_id = state.get("reimb_id", state.get("session_id", "unknown"))
    total = state.get("total_amount", 0)
    pdf_path = state.get("pdf_path", "")

    result = await send_approval_email(
        to_email="approver@company.com",
        reimb_id=reimb_id,
        total_amount=total,
        pdf_path=pdf_path,
    )

    return {"messages": [AIMessage(
        content=f"📧 报销单已提交审批！\n审批流程: 部门经理 → 财务审核 → 出纳付款\n请前往「进度查询」追踪状态。"
    )]}


async def query_status(state: ReimburseState) -> dict:
    """查询审批进度 — 智能判断单条查询 vs 列表查询"""
    reimb_id = state.get("reimb_id", "")
    entities = state.get("entities", {})
    sub_intent = state.get("sub_intent", "status_check")
    messages_list = state.get("messages", [])
    last_msg = messages_list[-1].content if messages_list else ""

    if not reimb_id and entities:
        reimb_id = entities.get("reimbursement_id", "")
    if not reimb_id:
        from app.agent.entities import _extract_uuid
        reimb_id = _extract_uuid(last_msg)

    # --- 路径 A：有具体报销单号 → 单条查询 ---
    if reimb_id:
        logger.info(f"Query single status for reimb_id={reimb_id}")
        from app.agent.tools.reimburse_tools import query_reimbursement_status as _qstatus
        result = await _qstatus(reimb_id=reimb_id)
        steps = result.get("steps", [])
        status_map = {"pending": "待审批", "approved": "已通过", "rejected": "已驳回", "returned": "已退回", "paid": "已付款"}
        status_cn = status_map.get(result.get("status", "pending"), "未知")

        if steps:
            text = "\n".join(
                f"  {s['step']}. {s['approver']} — {s['action']}"
                for s in steps
            )
        else:
            text = "  暂无审批记录"

        return {"messages": [AIMessage(
            content=f"📋 报销单 {reimb_id}\n状态: {status_cn}\n审批流程:\n{text}"
        )]}

    # --- 路径 B：无报销单号 → 多维度列表查询 ---
    logger.info(f"No reimb_id provided, doing multi-dimension search")

    # 从用户消息中抽取筛选条件
    status_filter = ""
    status_keywords = {
        "待审批": "pending", "待审": "pending",
        "已通过": "approved", "通过": "approved",
        "已驳回": "rejected", "驳回": "rejected",
        "已退回": "returned", "退回": "returned",
        "已付款": "paid", "已付": "paid", "付款": "paid",
    }
    for kw, val in status_keywords.items():
        if kw in last_msg:
            status_filter = val
            break

    # 从实体中提取部门/类型筛选
    dept_filter = entities.get("department", "")
    type_filter = entities.get("expense_type", "")

    # 从消息中提取金额筛选
    from app.agent.entities import _extract_amount as _ext_amt
    has_money_kw = any(k in last_msg for k in ["元", "¥", "￥"])
    amt_exact = _ext_amt(last_msg) if has_money_kw else None
    amt_min = None
    amt_max = None
    range_match = re.search(r'(?:大于|超过|>=|>)\s*(\d[\d,]*)', last_msg)
    if range_match:
        amt_min = float(range_match.group(1).replace(",", ""))
    range_match = re.search(r'(?:小于|低于|<=|<|不超过)\s*(\d[\d,]*)', last_msg)
    if range_match:
        amt_max = float(range_match.group(1).replace(",", ""))

    from app.agent.tools.reimburse_tools import query_reimbursement_status as _qsearch
    result = await _qsearch(
        status=status_filter,
        department=dept_filter,
        expense_type=type_filter,
        amount_min=amt_min,
        amount_max=amt_max,
        amount_exact=amt_exact,
        keyword=entities.get("description", "") or "",
        limit=30,
    )

    records = result.get("results", [])
    if not records:
        # 可能是按 ID 查询无结果的回退
        filters_used = [f for f in [status_filter, dept_filter, type_filter] if f]
        hint = f"（筛选条件: {', '.join(filters_used)}）" if filters_used else ""
        return {"messages": [AIMessage(
            content=f"📋 未找到符合条件的报销记录{hint}。\n\n可以说 \"我的报销记录\" 查看全部，或提供具体筛选条件。"
        )]}

    status_labels = {"pending": "待审批", "approved": "已通过", "rejected": "已驳回", "returned": "已退回", "paid": "已付款"}
    dept_map = {"travel": "差旅", "entertainment": "招待", "office": "办公", "other": "其他"}
    lines = [f"📋 找到 {len(records)} 条报销记录:\n"]
    for r in records[:15]:
        s = status_labels.get(r["status"], r["status"])
        t = dept_map.get(r.get("expense_type", ""), r.get("expense_type", ""))
        id_short = r["reimb_id"][:8] if r.get("reimb_id") else "?"
        lines.append(
            f"  [{s}] {t} ¥{r.get('total_amount', 0):,.2f} — {r.get('description', '')[:20]} "
            f"(#{id_short} {r.get('user_name', '')})"
        )
    if len(records) > 15:
        lines.append(f"  ... 还有 {len(records) - 15} 条，请输入更精确的筛选条件")
    lines.append(f"\n输入 \"查询 {records[0]['reimb_id'][:8] if records else ''}\" 查看单条详情")

    return {"messages": [AIMessage(content="\n".join(lines))]}


def approval_process(state: ReimburseState) -> dict:
    """审批流程处理"""
    logger.info("Processing approval action")
    return {"messages": [AIMessage(content="审批操作已记录，报销单状态已更新。")]}


async def modify_reimbursement(state: ReimburseState) -> dict:
    """
    修改/撤回报销单。

    仅允许撤回 status=pending 的报销单；
    已审批/已付款的报销单无法撤回。
    """
    entities = state.get("entities") or {}
    reimb_id = state.get("reimb_id", entities.get("reimbursement_id", ""))
    if not reimb_id:
        messages_list = state.get("messages", [])
        last_msg = messages_list[-1].content if messages_list else ""
        from app.agent.entities import _extract_uuid
        reimb_id = _extract_uuid(last_msg)

    if not reimb_id:
        return {"messages": [AIMessage(
            content="请提供要修改的报销单号，例如：\"撤回 a1b2c3d4\""
        )]}

    logger.info(f"Attempting to modify/cancel reimbursement {reimb_id}")
    try:
        from sqlalchemy import text
        from app.core.database import engine

        async with engine.connect() as conn:
            # 查当前状态
            r = await conn.execute(
                text("SELECT status FROM reimbursements WHERE id = :rid"), {"rid": reimb_id}
            )
            row = r.fetchone()
            if not row:
                return {"messages": [AIMessage(content=f"❌ 报销单 {reimb_id} 不存在。")]}

            current_status = row.status
            if current_status != "pending":
                return {"messages": [AIMessage(
                    content=f"❌ 报销单 {reimb_id} 当前状态为「{current_status}」，无法撤回。\n只有「待审批」状态的报销单可以撤回。"
                )]}

            # 撤回：设为 cancelled，退回预算
            await conn.execute(
                text("UPDATE reimbursements SET status = 'cancelled' WHERE id = :rid"),
                {"rid": reimb_id},
            )
            await conn.execute(
                text("UPDATE approval_records SET action = 'cancelled', comment = '申请人撤回' WHERE reimbursement_id = :rid"),
                {"rid": reimb_id},
            )
            await conn.commit()

        return {"messages": [AIMessage(
            content=f"✅ 报销单 {reimb_id} 已撤回。如需重新提交，请重新发起报销申请。"
        )]}
    except Exception as e:
        logger.error(f"Failed to modify reimbursement {reimb_id}: {e}")
        return {"messages": [AIMessage(content=f"❌ 撤回失败: {e}")]}


async def general_response(state: ReimburseState) -> dict:
    """
    通用回复 — RAG 增强 + 闲聊降级。

    1. 检索知识库获取相关上下文
    2. 命中 → 基于知识库回答
    3. 未命中 → LLM 自由对话，不强制报销主题
    """
    messages = state["messages"]
    last_msg = messages[-1].content if messages else "你好"

    from app.agent.knowledge.retriever import build_context_for_llm
    kb_context = build_context_for_llm(last_msg, top_k=2)
    has_kb = bool(kb_context and len(kb_context) > 20)

    if has_kb:
        prompt = GENERAL_CHAT_PROMPT.format(context=kb_context, user_query=last_msg)
    else:
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"知识库中没有找到与用户问题直接相关的内容。"
            f"请以友好、专业的财务助手身份自由回答。"
            f"不要编造不存在的政策条款。\n\n"
            f"用户: {last_msg}"
        )

    reply = await _try_llm_async([HumanMessage(content=prompt)])
    if reply:
        return {"messages": [AIMessage(content=reply)]}

    return {"messages": [AIMessage(
        content=f"你好！我是财务报销助手。\n\n"
                f"• 新建报销：\"我要报销差旅费 1500 元，部门技术部\"\n"
                f"• 查询所有：\"列出我的报销记录\" / \"有哪些待审批的？\"\n"
                f"• 查询进度：\"查询 a1b2c3d4 的审批进度\"\n"
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
        ("modify_reimbursement", modify_reimbursement),
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
        "modify_reimbursement": "modify_reimbursement",
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
    builder.add_edge("modify_reimbursement", END)
    builder.add_edge("policy_lookup", END)
    builder.add_edge("approval_process", END)
    builder.add_edge("general_response", END)

    return builder.compile()


reimburse_graph = build_graph()
logger.info(f"LangGraph v2.0 compiled ({len(reimburse_graph.nodes)} nodes, specialized reimbursement agent)")
