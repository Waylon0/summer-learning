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
# 是否配置了有效的 API Key（唯一的"永久"开关：仅当 Key 为占位符时才认为未配置）。
# 注意：不再使用运行时"熔断"永久禁用 LLM —— 每次调用都会重新尝试，
# 单次失败只影响该次请求，网络恢复后自动自愈。
_LLM_CONFIGURED = "sk-xxx" not in settings.OPENAI_API_KEY
llm = None


def llm_configured() -> bool:
    """LLM 是否已配置可用（供节点判断是否需要提示服务不可用）。"""
    return _LLM_CONFIGURED


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
            request_timeout=15,
            max_retries=2,
        )
    return llm


def _try_llm(messages: list) -> str:
    """尝试调用 LLM（同步版）。每次都真实尝试，失败仅影响本次调用。"""
    if not _LLM_CONFIGURED:
        return ""
    try:
        resp = _get_llm().invoke(messages)
        return resp.content
    except Exception as e:
        logger.warning(f"LLM call failed (sync, will retry next time): {str(e)[:150]}")
        return ""


async def _try_llm_async(messages: list) -> str:
    """尝试调用 LLM（异步版）。每次都真实尝试，失败仅影响本次调用，不永久禁用。"""
    if not _LLM_CONFIGURED:
        return ""
    try:
        resp = await _get_llm().ainvoke(messages)
        return resp.content
    except Exception as e:
        logger.warning(f"LLM call failed (async, will retry next time): {str(e)[:150]}")
        return ""


async def _try_llm_structured(messages: list, output_schema: type) -> dict | None:
    """LLM 结构化输出。每次都真实尝试，失败仅影响本次调用。"""
    if not _LLM_CONFIGURED:
        return None
    try:
        from langchain_openai import ChatOpenAI
        structured_llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
            temperature=0,
            request_timeout=15,
            max_retries=2,
        ).with_structured_output(output_schema, method="json_mode")
        resp = await structured_llm.ainvoke(messages)
        if isinstance(resp, dict):
            return resp
        if hasattr(resp, "model_dump"):
            return resp.model_dump()
        return resp
    except Exception as e:
        logger.info(f"LLM structured call failed (will retry next time): {str(e)[:150]}")
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
    budget_unavailable: bool
    # 输出
    invoices: list[dict]
    pdf_path: str
    status: str
    reimb_id: str
    save_failed: bool
    attachments: list[str]
    user_id: str
    user_name: str
    user_role: str
    user_department: str


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
            # 继承上一轮意图；把待补充的槽位作为 required_slots 传下去，
            # 便于 entity_extraction 重新校验（补齐则放行，仍缺则再次追问）。
            contextual_result = dict(contextual_intent)
            contextual_result["required_slots"] = list(ctx.missing_slots)
            return {
                "intent": contextual_intent["primary"],
                "sub_intent": contextual_intent.get("sub", "none"),
                "intent_result": contextual_result,
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
                "user_id": state.get("user_id", ""),
                "user_name": state.get("user_name", ""),
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
                "user_id": state.get("user_id", ""),
                "user_name": state.get("user_name", ""),
            }

    # --- 步骤1：规则关键词匹配（快速首过，来自意图注册表）---
    intent_result = classify_by_keywords(last_msg)

    # --- 步骤2：语义向量路由（NLP 层，抗自然语言表达变化；离线可兜底）---
    semantic_result = None
    try:
        from app.agent.semantic_router import get_semantic_router
        router = get_semantic_router()
        if router.available():
            semantic_result = router.route(last_msg)
            if semantic_result:
                logger.info(
                    f"Semantic route: {semantic_result.primary.value}/{semantic_result.sub.value} "
                    f"score={semantic_result.score:.3f} margin={semantic_result.margin:.3f}"
                )
    except Exception as e:
        logger.warning(f"Semantic router error (ignored): {e}")

    # --- 步骤3：LLM 语义分类（最强语义引擎）---
    from pydantic import BaseModel, Field
    class IntentOutput(BaseModel):
        primary: str = Field(default="general_chat")
        sub: str | None = Field(default="none")
        confidence: float = Field(default=0.8)

    llm_data = None
    structured = await _try_llm_structured(
        [HumanMessage(content=f"{INTENT_CLASSIFY_PROMPT}\n\n用户输入: {last_msg}")],
        IntentOutput,
    )
    if structured:
        llm_data = structured
        logger.info(f"LLM structured intent: {structured}")
    else:
        llm_response = await _try_llm_async([
            HumanMessage(content=f"{INTENT_CLASSIFY_PROMPT}\n\n用户输入: {last_msg}\n\nJSON:")
        ])
        if llm_response:
            content = llm_response.strip().lstrip("```json").rstrip("```").strip()
            try:
                llm_data = json.loads(content)
                logger.info(f"LLM enhanced intent: {llm_data}")
            except (json.JSONDecodeError, ValueError):
                llm_data = None

    # --- 步骤4：三层融合（规则 + 语义 + LLM，交叉印证降低误判）---
    from app.agent.intents import fuse_intents
    intent_result = fuse_intents(
        rule=intent_result,
        semantic=semantic_result,
        llm=llm_data,
        semantic_threshold=settings.INTENT_SEMANTIC_THRESHOLD,
        llm_trust=settings.INTENT_LLM_TRUST_THRESHOLD,
    )
    logger.info(f"Fused intent: {intent_result.primary.value}/{intent_result.sub.value} (source={intent_result.source} conf={intent_result.confidence:.2f})")

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
    # 合并上下文实体（新值优先，JWT 兜底）
    merged_entities = ReimbursementEntities(
        department=entities.department or dept or state.get("department", ""),
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
        "user_id": state.get("user_id", ""),
        "user_name": state.get("user_name", ""),
    }


# =============================================================================
# 意图路由
# =============================================================================
def route_by_intent(
    state: ReimburseState
) -> Literal[
    "entity_extraction", "query_status", "policy_lookup",
    "approval_process", "generate_reimbursement_doc",
    "modify_reimbursement", "general_response"
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

    # JWT 用户默认信息（优先级低于上下文，高于空值）
    state_dept = state.get("department") or ""
    state_type = state.get("expense_type") or ""
    state_desc = state.get("description") or ""

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

    # 合并实体（优先级: 用户消息 > 会话上下文 > JWT 默认值）
    merged = ReimbursementEntities(
        department=entities.department or context_dept or state_dept,
        expense_type=entities.expense_type or context_type or state_type,
        total_amount=entities.total_amount if entities.total_amount > 0 else context_amount,
        description=entities.description or context_desc or state_desc,
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
            "validation_result": {"passed": False, "errors": result.errors},
            "messages": [AIMessage(content=f"⚠️ 校验未通过:\n{errors_text}")],
        }

    if amount > 90000:
        logger.warning(
            BudgetExceededError(department=department, amount=amount, remaining=0).message
        )

    logger.info("Pre-validation passed")
    return {"validation_result": {"passed": True, "errors": []}}


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
        # 无附件是正常场景（用户口述金额报销），仅记录日志，不向用户发独立提示，
        # 避免流式模式下这条中间消息干扰最终的报销结果摘要。
        logger.info("🔍 No attachments — using user-provided amount")
        invoices = [{
            "invoice_code": "", "invoice_number": "", "invoice_date": "", "invoice_type": "",
            "buyer_name": "中国石油华东分公司", "buyer_tax_id": "91310000710913000J",
            "seller_name": "", "seller_tax_id": "",
            "amount": state.get("total_amount") or 0, "tax_amount": 0,
            "total_with_tax": state.get("total_amount") or 0,
            "items": [],
            "remarks": "", "payee": "", "reviewer": "", "drawer": "",
        }]
        return {"invoices": invoices}

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
        logger.warning(f"OCR produced no valid invoice from {len(attachments)} file(s) — falling back to user amount")
        invoices = [{
            "invoice_code": "", "invoice_number": "", "invoice_date": "", "invoice_type": "",
            "buyer_name": "中国石油华东分公司", "buyer_tax_id": "91310000710913000J",
            "seller_name": "", "seller_tax_id": "",
            "amount": state.get("total_amount") or 0, "tax_amount": 0,
            "total_with_tax": state.get("total_amount") or 0,
            "items": [],
            "remarks": "", "payee": "", "reviewer": "", "drawer": "",
        }]
        return {
            "invoices": invoices,
            "messages": [AIMessage(content="⚠️ 上传的票据未能成功识别，将按您提供的金额提交。")],
        }

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
    # 预算数据不可用（DB 故障 / 部门无预算配置）→ 明确提示，不继续入库
    if not result.get("available", True):
        logger.warning(f"Budget unavailable: {department} reason={result.get('error')}")
        return {
            "budget_result": result,
            "need_special_approval": False,
            "budget_unavailable": True,
            "messages": [AIMessage(content=f"⚠️ {result.get('message', '预算核对失败，请稍后重试。')}")],
        }
    need = result.get("need_special_approval", False)
    logger.info(f"Budget: {department} amount={total} exceeded={need}")
    return {"budget_result": result, "need_special_approval": need, "budget_unavailable": False}


# =============================================================================
# 预算检查后的路由
# =============================================================================
def route_after_budget(state: ReimburseState) -> Literal["save_to_db", "rejection_response", "halt"]:
    """
    预算检查后的路由:
      - 预算不可用 → halt（已给出提示，直接结束）
      - 硬拒绝 → rejection_response（不保存）
      - 超标/正常 → save_to_db（先入库再继续）
    """
    if state.get("budget_unavailable"):
        return "halt"
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
    user_id = state.get("user_id") or "anonymous"
    user_name = state.get("user_name") or "未知用户"
    # 尝试从会话上下文获取用户名
    if user_name == "未知用户" and user_id != "anonymous":
        from app.agent.sessions import get_session_store
        ctx = get_session_store().get_context(state.get("session_id", ""))
        if ctx and ctx.user_id == user_id and ctx.user_id:
            user_name = ctx.user_id  # fallback, real name from JWT
    if user_name == "未知用户":
        user_name = user_id  # 用 user_id 兜底

    logger.info(
        f"Saving to DB: dept={department} type={expense_type} "
        f"amount={total_amount} special={need_special}"
    )

    try:
        result = await save_reimbursement_to_db(
            department=department,
            expense_type=expense_type,
            total_amount=total_amount,
            invoices=invoices,
            need_special_approval=need_special,
            budget_remaining_after=budget_remaining,
            description=description,
            user_id=user_id,
            user_name=user_name,
        )
    except Exception as e:
        logger.error(f"报销单入库失败: {e}")
        return {
            "status": "error",
            "reimb_id": "",
            "save_failed": True,
            "messages": [AIMessage(content="⚠️ 报销单保存失败，数据库暂时不可用，请稍后重试。")],
        }

    reimb_id = result.get("reimb_id", "")
    logger.info(f"Saved: reimb_id={reimb_id}")

    return {
        "status": result.get("status", "pending"),
        "reimb_id": reimb_id,
        "save_failed": False,
        "messages": [AIMessage(content=f"✅ 报销单已创建 (单号: {reimb_id})")],
    }


def route_after_save(state: ReimburseState) -> Literal["special_approval", "generate_pdf", "halt"]:
    """保存后：失败→结束；超标→特殊审批；正常→生成PDF"""
    if state.get("save_failed"):
        return "halt"
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
async def special_approval(state: ReimburseState) -> dict:
    """
    标记特殊审批 —— 预算超标时触发（此时报销单已入库，need_special_approval=True）。
    追加一条审批流转记录，标记进入财务总监特批队列。
    """
    logger.warning("Budget exceeded — special approval required")
    reimb_id = state.get("reimb_id", "")
    department = state.get("department", "")
    total = state.get("total_amount", 0)

    # 追加特殊审批流转记录（幂等失败不阻断主流程）
    if reimb_id:
        try:
            from app.core.database import engine
            from sqlalchemy import text
            import uuid as _uuid
            async with engine.begin() as conn:
                step_row = await conn.execute(
                    text("SELECT COALESCE(MAX(step),0)+1 AS s FROM approval_records WHERE reimbursement_id = :rid"),
                    {"rid": reimb_id},
                )
                step = step_row.fetchone().s
                await conn.execute(text("""
                    INSERT INTO approval_records (id, reimbursement_id, approver, step, action, comment)
                    VALUES (:id, :rid, '财务总监', :step, 'pending', '预算超标，转特殊审批队列')
                """), {"id": _uuid.uuid4().hex[:12], "rid": reimb_id, "step": step})
            logger.info(f"Special approval record added: reimb={reimb_id}")
        except Exception as e:
            logger.error(f"特殊审批记录写入失败（不阻断）: {e}")

    return {"messages": [AIMessage(
        content=(
            f"⚠️ 预算超标！该报销已标记为特殊审批流程。\n"
            f"报销单号: {reimb_id}\n"
            f"部门: {department}\n"
            f"金额: ¥{total:,.2f}\n"
            f"已转财务总监特批队列，请等待额外审批。"
        )
    )]}


def rejection_response(state: ReimburseState) -> dict:
    """
    硬拒绝响应 —— 违反 Level 1 合规规则时（发生在入库之前，故无需更新数据库）。
    记录违规日志并向用户说明原因。
    """
    from app.core.exceptions import ComplianceViolationError
    compliance = state.get("compliance_result") or {}
    errors = compliance.get("errors", ["违反公司费用政策"]) if compliance else ["校验未通过"]
    reasons = "\n".join(f"• {e}" for e in errors)
    total = state.get("total_amount", 0)
    etype = state.get("expense_type", "other")
    department = state.get("department", "")
    logger.error(
        f"报销被拒(合规): dept={department} type={etype} amount={total} reasons={errors}"
    )
    return {"status": "rejected", "messages": [AIMessage(
        content=f"🚫 报销申请被拒绝，原因:\n{reasons}\n\n如有疑问请联系财务部，或修正后重新提交。"
    )]}


async def generate_pdf(state: ReimburseState) -> dict:
    """生成 PDF 报销单（CPU 密集型任务放线程池，不阻塞事件循环）。失败时不阻断流程。"""
    import asyncio
    total = state.get("total_amount", 0)
    invoices = state.get("invoices") or []

    try:
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
    except Exception as e:
        logger.error(f"PDF 生成失败（不阻断，继续提交审批）: {e}")
        # PDF 仅为附件，失败不应阻断报销主流程
        return {"pdf_path": "", "messages": [AIMessage(content="ℹ️ 报销单 PDF 生成失败，但报销申请已保存，可稍后重新下载。")]}


async def send_email(state: ReimburseState) -> dict:
    """发送审批邮件，并返回一条完整的报销结果摘要作为最终答复。"""
    reimb_id = state.get("reimb_id", state.get("session_id", "unknown"))
    total = state.get("total_amount", 0)
    pdf_path = state.get("pdf_path", "")
    department = state.get("department", "") or "—"
    expense_type = state.get("expense_type", "") or "other"
    need_special = state.get("need_special_approval", False)

    result = await send_approval_email(
        to_email="approver@company.com",
        reimb_id=reimb_id,
        total_amount=total,
        pdf_path=pdf_path,
    )

    # 费用类型中文标签（未知类型回退为原始值）
    type_labels = {
        "travel": "差旅费", "entertainment": "招待费", "office": "办公用品",
        "communication": "通信费", "transport": "市内交通费", "meeting": "会议费",
        "training": "培训费", "other": "其他费用",
        "rd_materials": "研发材料费", "rd_equipment": "研发设备费",
        "tech_acquisition": "技术引进费", "software_license": "软件许可费",
        "advertisement": "广告推广费", "exhibition": "展会费",
        "client_maintenance": "客户维护费", "audit": "审计服务费",
        "recruitment": "招聘费", "renovation": "装修费", "cloud_service": "云服务费",
    }
    type_cn = type_labels.get(expense_type, expense_type)

    approval_note = (
        "审批流程: 部门经理 → 财务总监特批 → 出纳付款（⚠️ 预算超标，已转特殊审批）"
        if need_special
        else "审批流程: 部门经理 → 财务审核 → 出纳付款"
    )

    summary = (
        f"📧 报销单已提交审批！\n"
        f"• 报销单号: {reimb_id}\n"
        f"• 部门: {department}\n"
        f"• 费用类型: {type_cn}\n"
        f"• 报销金额: ¥{total:,.2f}\n"
        f"{approval_note}\n"
        f"请前往「进度查询」追踪状态。"
    )

    return {"messages": [AIMessage(content=summary)]}


async def query_status(state: ReimburseState) -> dict:
    """
    查询报销单 —— 动态查询规划器版（安全 + 权限）。

    路径:
      A. 用户提供了报销单号 → 查单条详情（含权限校验，不可越权看他人）
      B. 否则 → LLM 把自然语言解析成结构化查询计划，
         经安全清洗 + 强制权限过滤后，参数化执行 SELECT。

    安全保证:
      - 绝不执行 LLM 生成的 SQL；LLM 只产出结构化 JSON 计划。
      - 所有条件白名单校验 + ORM 参数化，免疫注入。
      - 权限在代码层强制注入：员工只看本人、经理只看本部门、管理员/财务全局。
    """
    from app.core.database import AsyncSessionLocal
    from app.agent.query_planner import (
        sanitize_plan, rule_extract_plan, extract_plan_with_llm,
        execute_plan, apply_permission_scope, QueryPlan,
        STATUS_LABELS, TYPE_LABELS,
    )

    entities = state.get("entities", {})
    messages_list = state.get("messages", [])
    last_msg = messages_list[-1].content if messages_list else ""

    user_id = state.get("user_id", "")
    user_role = state.get("user_role", "")
    user_department = state.get("user_department", "")

    reimb_id = state.get("reimb_id", "")
    if not reimb_id and entities:
        reimb_id = entities.get("reimbursement_id", "")
    if not reimb_id:
        from app.agent.entities import _extract_uuid
        reimb_id = _extract_uuid(last_msg)

    # --- 路径 A：具体报销单号 → 单条查询（带权限校验）---
    if reimb_id:
        logger.info(f"Query single status for reimb_id={reimb_id} role={user_role}")
        from app.agent.tools.reimburse_tools import query_reimbursement_status as _qstatus
        result = await _qstatus(reimb_id=reimb_id)

        if result.get("status") in ("not_found", "unknown"):
            return {"messages": [AIMessage(content=f"📋 未找到报销单 {reimb_id}。")]}

        # 权限校验：员工只能看自己、经理只能看本部门
        role = (user_role or "").lower()
        owner_dept = result.get("department", "")
        owner_uid = result.get("user_id", "")
        if role == "employee":
            # 单条查询工具未返回 user_id 时，用 DB 再确认归属
            if owner_uid and owner_uid != user_id:
                return {"messages": [AIMessage(content="⛔ 您只能查询本人的报销单。")]}
            if not owner_uid:
                async with AsyncSessionLocal() as _db:
                    from app.models.reimbursement import Reimbursement as _R
                    _r = await _db.get(_R, reimb_id)
                    if _r and _r.user_id != user_id:
                        return {"messages": [AIMessage(content="⛔ 您只能查询本人的报销单。")]}
        elif role == "manager":
            if owner_dept and owner_dept != user_department:
                return {"messages": [AIMessage(content=f"⛔ 您只能查询本部门（{user_department}）的报销单。")]}
        elif role not in ("admin", "finance"):
            return {"messages": [AIMessage(content="⛔ 您尚未登录，无法查询报销单。")]}

        steps = result.get("steps", [])
        status_cn = STATUS_LABELS.get(result.get("status", "pending"), "未知")
        type_cn = TYPE_LABELS.get(result.get("expense_type", ""), result.get("expense_type", ""))
        if steps:
            steps_text = "\n".join(
                f"  {s['step']}. {s['approver']} — {s['action']}" for s in steps
            )
        else:
            steps_text = "  暂无审批记录"
        return {"messages": [AIMessage(
            content=(
                f"📋 报销单 {reimb_id}\n"
                f"部门: {result.get('department','')}  类型: {type_cn}\n"
                f"金额: ¥{result.get('total_amount',0):,.2f}\n"
                f"状态: {status_cn}\n审批流程:\n{steps_text}"
            )
        )]}

    # --- 路径 B：无报销单号 → 动态查询规划 ---
    # 1) LLM 解析查询计划（失败 → 规则兜底）
    raw_plan = await extract_plan_with_llm(last_msg, _try_llm_async)
    if raw_plan is None:
        raw_plan = rule_extract_plan(last_msg)
        logger.info(f"[QueryPlanner] rule fallback plan: {raw_plan}")
    else:
        logger.info(f"[QueryPlanner] LLM plan: {raw_plan}")

    # 合并 entity_extraction 已识别到的实体（作为补充，不覆盖 LLM 明确结果）
    if entities.get("expense_type") and "expense_type" not in raw_plan:
        raw_plan["expense_type"] = entities["expense_type"]

    plan = sanitize_plan(raw_plan)

    # 2) 安全执行（强制权限过滤）
    async with AsyncSessionLocal() as db:
        records, total, notice = await execute_plan(
            db, plan, user_id=user_id, user_role=user_role, user_department=user_department,
        )

    # 3) 组织回复
    prefix = f"ℹ️ {notice}\n\n" if notice else ""
    if not records:
        return {"messages": [AIMessage(
            content=(
                f"{prefix}📋 未找到符合条件的报销记录。\n"
                f"筛选条件: {plan.to_summary()}\n\n"
                f"可以换个条件，或说\"我的全部报销\"查看所有。"
            )
        )]}

    lines = [f"{prefix}📋 找到 {total} 条报销记录（筛选: {plan.to_summary()}）:\n"]
    for r in records[:15]:
        s = STATUS_LABELS.get(r["status"], r["status"])
        t = TYPE_LABELS.get(r.get("expense_type", ""), r.get("expense_type", ""))
        id_short = r["reimb_id"][:8] if r.get("reimb_id") else "?"
        lines.append(
            f"  [{s}] {t} ¥{r.get('total_amount', 0):,.2f} — "
            f"{r.get('description', '')[:20]} (#{id_short} {r.get('user_name', '')})"
        )
    if total > 15:
        lines.append(f"  ... 还有 {total - 15} 条，请缩小筛选范围或指定排序")
    lines.append(f"\n输入 \"查询 {records[0]['reimb_id'][:8]}\" 查看单条详情")

    return {"messages": [AIMessage(content="\n".join(lines))]}


async def approval_process(state: ReimburseState) -> dict:
    """
    审批操作处理 —— 真正写库并变更状态（含权限校验）。

    权限:
      - employee: 无审批权 → 拒绝
      - manager : 只能审批本部门报销单
      - admin/finance: 可跨部门审批
    动作识别: 从用户消息中解析 通过/驳回/退回 + 报销单号。
    """
    from app.agent.entities import _extract_uuid
    from app.core.database import AsyncSessionLocal
    from app.services.reimbursement_svc import ApprovalService
    from app.models.reimbursement import Reimbursement
    from app.core.exceptions import ReimbursementNotFoundError, BusinessException
    from app.agent.query_planner import STATUS_LABELS

    messages_list = state.get("messages", [])
    last_msg = messages_list[-1].content if messages_list else ""
    entities = state.get("entities") or {}

    user_id = state.get("user_id", "")
    user_name = state.get("user_name", "") or "审批人"
    user_role = (state.get("user_role", "") or "").lower()
    user_department = state.get("user_department", "")

    # --- 权限：员工无审批权 ---
    if user_role not in ("manager", "admin", "finance"):
        if not user_role:
            return {"messages": [AIMessage(content="⛔ 您尚未登录，无法执行审批操作。")]}
        return {"messages": [AIMessage(content="⛔ 您没有审批权限，只有部门经理或管理员可以审批。")]}

    # --- 解析报销单号 ---
    reimb_id = state.get("reimb_id", "") or entities.get("reimbursement_id", "") or _extract_uuid(last_msg)
    if not reimb_id:
        return {"messages": [AIMessage(content=(
            "请提供要审批的报销单号，例如：\"通过 6441a34d638d\" 或 \"驳回 6441a34d638d，金额超标\"。"
        ))]}

    # --- 解析审批动作 ---
    action = ""
    if any(k in last_msg for k in ["通过", "同意", "批准", "approve"]):
        action = "approve"
    elif any(k in last_msg for k in ["驳回", "拒绝", "不通过", "reject"]):
        action = "reject"
    elif any(k in last_msg for k in ["退回", "打回", "return"]):
        action = "return"
    if not action:
        return {"messages": [AIMessage(content=(
            f"请说明审批动作（通过/驳回/退回），例如：\"通过 {reimb_id[:8]}\"。"
        ))]}

    # --- 审批意见（可选）：取消息中逗号后的部分 ---
    comment = ""
    for sep in ["，", ",", "：", ":"]:
        if sep in last_msg:
            tail = last_msg.split(sep, 1)[1].strip()
            if tail and not _extract_uuid(tail):
                comment = tail
                break

    async with AsyncSessionLocal() as db:
        # 权限：经理只能审批本部门
        reimb = await db.get(Reimbursement, reimb_id)
        if not reimb:
            return {"messages": [AIMessage(content=f"📋 未找到报销单 {reimb_id}。")]}
        if user_role == "manager" and reimb.department != user_department:
            return {"messages": [AIMessage(
                content=f"⛔ 您只能审批本部门（{user_department}）的报销单，该单属于 {reimb.department}。"
            )]}
        if reimb.status != "pending":
            cn = STATUS_LABELS.get(reimb.status, reimb.status)
            return {"messages": [AIMessage(
                content=f"⚠️ 报销单 {reimb_id} 当前状态为「{cn}」，只有「待审批」的单子才能审批。"
            )]}

        svc = ApprovalService(db)
        try:
            record = await svc.record(reimb_id, user_name, action, comment or None)
        except (ReimbursementNotFoundError, BusinessException) as e:
            return {"messages": [AIMessage(content=f"⚠️ 审批失败：{e.message}")]}
        except Exception as e:
            logger.error(f"审批写库失败: {e}")
            return {"messages": [AIMessage(content="⚠️ 审批操作失败，请稍后重试。")]}

    action_cn = {"approve": "已通过", "reject": "已驳回", "return": "已退回"}[action]
    logger.info(f"Approval done: reimb={reimb_id} action={action} by={user_name}")
    return {"status": record and action, "reimb_id": reimb_id, "messages": [AIMessage(content=(
        f"✅ 审批完成！\n"
        f"• 报销单号: {reimb_id}\n"
        f"• 审批结果: {action_cn}\n"
        f"• 审批人: {user_name}\n"
        + (f"• 审批意见: {comment}\n" if comment else "")
    ))]}


async def generate_reimbursement_doc(state: ReimburseState) -> dict:
    """
    为一张【已存在的报销单】生成结构化报销单 PDF 并返回下载链接。

    报销单号来源优先级:
      1. 用户消息 / 实体中明确的报销单号
      2. 本次会话上下文中最近创建的报销单号（state.reimb_id）
    权限:
      - employee: 仅可为本人报销单生成
      - manager : 仅可为本部门报销单生成
      - admin/finance: 全部
    注意: 系统不再生成"发票"，发票仅作为输入数据供 OCR 提取。
    """
    from app.agent.entities import _extract_uuid
    from app.core.database import AsyncSessionLocal
    from app.services.reimbursement_svc import ReimbursementService
    from app.services.pdf_svc import generate_and_store_reimbursement_pdf
    from app.core.exceptions import ReimbursementNotFoundError
    from app.agent.query_planner import STATUS_LABELS, TYPE_LABELS

    messages_list = state.get("messages", [])
    last_msg = messages_list[-1].content if messages_list else ""
    entities = state.get("entities") or {}

    user_id = state.get("user_id", "")
    user_role = (state.get("user_role", "") or "").lower()
    user_department = state.get("user_department", "")

    # 报销单号：消息/实体 > 会话上下文最近一单
    reimb_id = (
        _extract_uuid(last_msg)
        or entities.get("reimbursement_id", "")
        or state.get("reimb_id", "")
    )
    if not reimb_id:
        return {"messages": [AIMessage(content=(
            "请提供要生成报销单 PDF 的报销单号，例如：\"下载报销单 6441a34d\"。\n"
            "如果您刚提交了报销，可以直接说\"生成刚才的报销单PDF\"。"
        ))]}

    async with AsyncSessionLocal() as db:
        svc = ReimbursementService(db)
        try:
            reimb = await svc.get_by_id(reimb_id)
        except ReimbursementNotFoundError:
            return {"messages": [AIMessage(content=f"📋 未找到报销单 {reimb_id}。")]}

        # 权限校验
        if user_role == "employee" and reimb.user_id != user_id:
            return {"messages": [AIMessage(content="⛔ 您只能为本人的报销单生成 PDF。")]}
        if user_role == "manager" and reimb.department != user_department:
            return {"messages": [AIMessage(content=f"⛔ 您只能为本部门（{user_department}）的报销单生成 PDF。")]}
        if user_role not in ("employee", "manager", "admin", "finance"):
            return {"messages": [AIMessage(content="⛔ 您尚未登录，无法生成报销单 PDF。")]}

        try:
            info = await generate_and_store_reimbursement_pdf(reimb)
        except Exception as e:
            logger.error(f"报销单 PDF 生成失败: {e}")
            return {"messages": [AIMessage(content="⚠️ 报销单 PDF 生成失败，请稍后重试。")]}

    type_cn = TYPE_LABELS.get(reimb.expense_type, reimb.expense_type)
    status_cn = STATUS_LABELS.get(reimb.status, reimb.status)
    logger.info(f"Reimbursement PDF generated via agent: reimb={reimb_id} object={info['object_name']}")
    return {"messages": [AIMessage(content=(
        f"📄 报销单 PDF 已生成！\n"
        f"• 报销单号: {reimb.id}\n"
        f"• 申请人: {reimb.user_name}\n"
        f"• 部门: {reimb.department}\n"
        f"• 费用类型: {type_cn}\n"
        f"• 金额: ¥{float(reimb.total_amount):,.2f}\n"
        f"• 状态: {status_cn}\n"
        f"• 下载地址: {info['download_url']}"
    ))]}


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
    通用回复 — 用户信息查询 + RAG 增强 + 闲聊降级。

    1. 检测用户信息查询 (我是谁/我的部门/我的信息等)
    2. RAG 检索知识库
    3. LLM 自由对话
    """
    messages = state["messages"]
    last_msg = messages[-1].content if messages else "你好"

    # ---- 用户信息查询检测 ----
    user_info_keywords = ["我是谁", "我的信息", "我的部门", "我在哪个部门", "我的身份", "你是谁",
                          "我的角色", "我的权限", "列出我的信息", "个人信息", "当前用户",
                          "我是哪个部门", "我属于哪个部门", "我是什么角色", "查看我的信息",
                          "所属部门", "什么部门", "哪个部门"]
    is_user_query = any(kw in last_msg for kw in user_info_keywords)
    # 额外检测：以"我"开头且包含"部门"的短消息
    if not is_user_query and last_msg.strip().startswith("我") and "部门" in last_msg and len(last_msg) < 20:
        is_user_query = True

    if is_user_query:
        user_id = state.get("user_id") or ""
        user_name = state.get("user_name") or ""
        user_dept = state.get("department") or ""
        role_map = {"employee": "普通员工", "manager": "部门经理", "admin": "系统管理员"}
        role_cn = role_map.get(state.get("role", ""), "未知")
        logger.info(f"User query: user_id={user_id[:8] if user_id else 'EMPTY'} name={user_name} dept={user_dept}")

        # DB fallback
        if not user_name and user_id:
            try:
                from sqlalchemy import text
                from app.core.database import engine
                async with engine.connect() as conn:
                    r = await conn.execute(text("SELECT name, department, role FROM users WHERE id = :uid"), {"uid": user_id})
                    row = r.fetchone()
                    if row:
                        user_name = row.name or user_name
                        user_dept = row.department or user_dept
                        role_cn = role_map.get(row.role, "未知")
            except Exception:
                pass

        if user_id:
            return {"messages": [AIMessage(
                content=(
                    f"👤 您的个人信息：\n\n"
                    f"• 姓名：{user_name}\n"
                    f"• 部门：{user_dept}\n"
                    f"• 角色：{role_cn}\n"
                    f"• 用户ID：{user_id[:8]}...\n\n"
                    f"如需修改信息，请联系系统管理员。"
                )
            )]}
        return {"messages": [AIMessage(
            content=f"⚠️ 您当前未登录，无法获取个人信息。\n请先登录后再查询。"
        )]}

    # ---- RAG + LLM 通用回复 ----
    from app.agent.knowledge.retriever import build_context_for_llm
    kb_context = build_context_for_llm(last_msg, top_k=2)
    has_kb = bool(kb_context and len(kb_context) > 20)

    if has_kb:
        prompt = GENERAL_CHAT_PROMPT.format(context=kb_context, user_query=last_msg)
    else:
        prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"知识库中没有找到与用户问题直接相关的内容。\n"
            f"请判断用户问题是否与报销/财务/费用/发票/审批相关：\n"
            f"- 相关：以友好专业的态度自然回答，不编造不存在的政策条款。\n"
            f"- 完全无关（如闲聊、写代码、通用百科、天气等）：委婉说明你专注于报销财务事务，"
            f"不便回答该问题，并温和引导用户提出报销相关需求（不要生硬拒绝）。\n\n"
            f"用户: {last_msg}"
        )

    reply = await _try_llm_async([HumanMessage(content=prompt)])
    if reply:
        return {"messages": [AIMessage(content=reply)]}

    # LLM 不可用时的兜底（无法生成自然语言，返回能力引导）
    return {"messages": [AIMessage(
        content=f"你好！我是财务报销助手，专注于报销与财务相关事务。\n\n"
                f"我可以帮您：\n"
                f"• 新建报销：\"我要报销差旅费 1500 元，部门技术部\"\n"
                f"• 查询记录：\"列出我的报销记录\" / \"有哪些待审批的？\"\n"
                f"• 查询进度：\"查询 a1b2c3d4 的审批进度\"\n"
                f"• 政策咨询：\"差旅费标准是多少？\"\n"
                f"• 生成票据：\"生成一张 1500 元的差旅费发票\"\n"
                f"• 上传票据：直接上传发票文件即可识别\n\n"
                f"请问有什么报销相关的需求可以帮您？"
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
        ("generate_reimbursement_doc", generate_reimbursement_doc),
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
        "approval_process": "approval_process",
        "generate_reimbursement_doc": "generate_reimbursement_doc",
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

    # 预算检查后：超标/正常 → 先入库 → 再走后续流程；硬拒绝 → 直接拒绝；预算不可用 → 直接结束
    builder.add_conditional_edges("budget_control", route_after_budget, {
        "save_to_db": "save_to_db",
        "rejection_response": "rejection_response",
        "halt": END,
    })

    builder.add_conditional_edges("save_to_db", route_after_save, {
        "special_approval": "special_approval",
        "generate_pdf": "generate_pdf",
        "halt": END,
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
    builder.add_edge("generate_reimbursement_doc", END)
    builder.add_edge("general_response", END)

    return builder.compile()


reimburse_graph = build_graph()
logger.info(f"LangGraph v2.0 compiled ({len(reimburse_graph.nodes)} nodes, specialized reimbursement agent)")
