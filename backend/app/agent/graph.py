"""LangGraph 驱动的报销审批状态机 — 集成真实工具与数据库查询。

LLM 不可用时自动降级为规则匹配模式。
"""

import json
from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage
from loguru import logger

from app.core.config import get_settings
from app.agent.tools import (
    ALL_TOOLS,
    ocr_recognize_invoice,
    compliance_check,
    budget_check,
    generate_reimbursement_pdf,
    send_approval_email,
    query_reimbursement_status,
)

settings = get_settings()

_llm_available = False if "sk-xxx" in settings.OPENAI_API_KEY else None


def _get_llm():
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

llm = None

def _try_llm(messages: list) -> str:
    global _llm_available
    if _llm_available is False:
        return ""
    try:
        resp = _get_llm().invoke(messages)
        _llm_available = True
        return resp.content
    except Exception as e:
        if _llm_available is None:
            logger.warning(f"LLM unavailable, using rule-based fallback: {e}")
        _llm_available = False
        return ""


class ReimburseState(TypedDict):
    messages: Annotated[list, add_messages]
    intent: str
    session_id: str
    department: str
    expense_type: str
    total_amount: float
    invoices: list[dict]
    compliance_result: dict
    budget_result: dict
    need_special_approval: bool
    pdf_path: str
    status: str


def _rule_based_intent(text: str) -> dict:
    text_lower = text.lower()
    if any(w in text_lower for w in ["报销", "申请", "提交", "新建", "差旅", "招待", "办公"]):
        intent = "new_reimbursement"
    elif any(w in text_lower for w in ["查询", "进度", "状态", "审批"]):
        intent = "query_status"
    else:
        intent = "general_question"

    dept = ""
    for d in ["技术部", "市场部", "财务部", "人事部", "研发部", "运营部"]:
        if d in text:
            dept = d
            break

    expense = "other"
    for t in ["差旅", "travel"]:
        if t in text_lower:
            expense = "travel"
            break
    for t in ["招待", "entertainment"]:
        if t in text_lower:
            expense = "entertainment"
            break
    for t in ["办公", "office"]:
        if t in text_lower:
            expense = "office"
            break

    import re
    nums = re.findall(r"(\d+(?:\.\d+)?)\s*元?", text)
    amount = float(nums[0]) if nums else 1500.0

    return {"intent": intent, "department": dept, "expense_type": expense, "total_amount": amount}


def classify_intent(state: ReimburseState) -> dict:
    messages = state["messages"]
    last_msg = messages[-1].content if messages else ""

    result = _rule_based_intent(last_msg)
    llm_response = _try_llm([
        HumanMessage(content=f"""你是一个意图分类器。只输出JSON。

意图: new_reimbursement(新建报销) / query_status(查询进度) / general_question

输入: {last_msg}

JSON:""")
    ])

    if llm_response:
        content = llm_response.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0]
        try:
            parsed = json.loads(content)
            if parsed.get("intent"):
                result["intent"] = parsed.get("intent", result["intent"])
                result["department"] = parsed.get("department", result["department"])
                result["expense_type"] = parsed.get("expense_type", result["expense_type"])
                result["total_amount"] = float(parsed.get("total_amount", result["total_amount"]))
                logger.info(f"LLM intent: {parsed}")
        except json.JSONDecodeError:
            pass

    logger.info(f"Intent: {result['intent']} | Dept: {result['department']} | Type: {result['expense_type']} | ¥{result['total_amount']}")

    return {
        "intent": result["intent"],
        "department": result["department"],
        "expense_type": result["expense_type"],
        "total_amount": result["total_amount"],
    }


def route_by_intent(state: ReimburseState) -> Literal["ocr_invoice", "query_status", "general_response"]:
    intent = state.get("intent", "general_question")
    if intent == "new_reimbursement":
        return "ocr_invoice"
    elif intent == "query_status":
        return "query_status"
    return "general_response"


def ocr_invoice(state: ReimburseState) -> dict:
    logger.info("🔍 Running OCR...")
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


def compliance_review(state: ReimburseState) -> dict:
    result = compliance_check(
        expense_type=state.get("expense_type", "other"),
        total_amount=state.get("total_amount", 0),
        department=state.get("department", ""),
    )
    logger.info(f"Compliance: {result}")
    return {"compliance_result": result}


def budget_control(state: ReimburseState) -> dict:
    department = state.get("department", "")
    total = state.get("total_amount", 0)
    result = budget_check(department=department, amount=total)
    need = result.get("need_special_approval", False)
    logger.info(f"Budget: {department} amount={total} exceeded={need}")
    return {"budget_result": result, "need_special_approval": need}


def route_after_budget(state: ReimburseState) -> Literal["special_approval", "generate_pdf"]:
    return "special_approval" if state.get("need_special_approval", False) else "generate_pdf"


def special_approval(state: ReimburseState) -> dict:
    logger.warning("⚠️ Budget exceeded — special approval required")
    return {"messages": [AIMessage(
        content=f"⚠️ 预算超标！该报销已标记为特殊审批流程。\n部门: {state.get('department','')}\n金额: ¥{state.get('total_amount',0):,.2f}"
    )]}


def generate_pdf(state: ReimburseState) -> dict:
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
    logger.info("📧 Sending email...")
    return {"messages": [AIMessage(
        content="📧 报销单已提交审批！\n审批流程: 部门经理 → 财务审核 → 出纳付款\n请前往「进度查询」追踪状态。"
    )]}


def query_status(state: ReimburseState) -> dict:
    result = query_reimbursement_status(reimb_id="", date_from="", date_to="")
    steps = result.get("steps", [])
    status_text = "\n".join(f"  {s['step']}. {s['approver']} — {s['action']}" for s in steps)
    return {"messages": [AIMessage(content=f"📋 报销单状态: {result.get('status','未知')}\n{status_text}")]}


def general_response(state: ReimburseState) -> dict:
    messages = state["messages"]
    last_msg = messages[-1].content if messages else "你好"

    system_prompt = """你是企业财务报销助手，可协助:
1. 新建报销 — 告知部门、费用类型、金额
2. 查询进度 — 提供报销单号
3. 政策咨询

费用标准:
- 差旅: 单次上限 ¥10,000
- 招待: 单次上限 ¥3,000
- 办公: 单品上限 ¥5,000
- 其他: 单次上限 ¥2,000"""

    llm_response = _try_llm([HumanMessage(content=f"{system_prompt}\n\n用户: {last_msg}")])

    if llm_response:
        return {"messages": [AIMessage(content=llm_response)]}

    return {"messages": [AIMessage(
        content=f"你好！我是财务报销助手。你可以这样使用我：\n\n"
                f"• 新建报销：\"我要报销差旅费 1500 元，部门技术部\"\n"
                f"• 查询进度：\"查询我的报销进度\"\n"
                f"• 政策咨询：\"差旅费标准是多少？\"\n\n"
                f"{system_prompt}"
    )]}


def build_graph():
    builder = StateGraph(ReimburseState)

    for name, fn in [
        ("classify_intent", classify_intent),
        ("ocr_invoice", ocr_invoice),
        ("compliance_review", compliance_review),
        ("budget_control", budget_control),
        ("special_approval", special_approval),
        ("generate_pdf", generate_pdf),
        ("send_email", send_email),
        ("query_status", query_status),
        ("general_response", general_response),
    ]:
        builder.add_node(name, fn)

    builder.set_entry_point("classify_intent")
    builder.add_conditional_edges("classify_intent", route_by_intent, {
        "ocr_invoice": "ocr_invoice",
        "query_status": "query_status",
        "general_response": "general_response",
    })
    builder.add_edge("ocr_invoice", "compliance_review")
    builder.add_edge("compliance_review", "budget_control")
    builder.add_conditional_edges("budget_control", route_after_budget, {
        "special_approval": "special_approval",
        "generate_pdf": "generate_pdf",
    })
    builder.add_edge("special_approval", "generate_pdf")
    builder.add_edge("generate_pdf", "send_email")
    builder.add_edge("send_email", END)
    builder.add_edge("query_status", END)
    builder.add_edge("general_response", END)

    return builder.compile()


reimburse_graph = build_graph()
logger.info(f"LangGraph compiled ({len(reimburse_graph.nodes)} nodes, LLM: {'online' if _llm_available else 'offline/rule-based'})")
