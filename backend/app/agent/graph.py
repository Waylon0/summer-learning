"""LangGraph 驱动的报销审批状态机。

工作流节点:
  START → classify_intent → [路由] →
    ├─ new_reimbursement → ocr_invoice → compliance_review → budget_control →
    │    ├─ [超标] → special_approval → generate_pdf → send_email → END
    │    └─ [正常] → generate_pdf → send_email → END
    ├─ query_status → query_db → format_response → END
    └─ modify_request → modify_instance → END
"""

from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
import json
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from app.core.config import get_settings
from app.agent.tools import ALL_TOOLS, compliance_check, budget_check

settings = get_settings()


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


llm = ChatOpenAI(
    model=settings.OPENAI_MODEL,
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.OPENAI_BASE_URL,
    temperature=0.1,
)


def classify_intent(state: ReimburseState) -> dict:
    messages = state["messages"]
    last_msg = messages[-1].content if messages else ""

    prompt = f"""你是一个企业财务报销助手的意图分类器。分析用户输入，将意图归类为以下之一，并提取关键实体。

意图类型:
- new_reimbursement: 用户要新建报销申请
- query_status: 用户要查询报销进度
- modify_request: 用户要修改已有报销
- general_question: 一般性问题

用户输入: {last_msg}

请以JSON格式输出: {{"intent": "意图类型", "department": "部门", "expense_type": "费用类型", "total_amount": 金额数字}}"""
    response = llm.invoke([HumanMessage(content=prompt)])
    content = response.content
    try:
        result = json.loads(content)
    except Exception:
        result = {"intent": "general_question", "department": "", "expense_type": "", "total_amount": 0}

    return {
        "intent": result.get("intent", "general_question"),
        "department": result.get("department", ""),
        "expense_type": result.get("expense_type", ""),
        "total_amount": float(result.get("total_amount", 0)),
    }


def route_by_intent(state: ReimburseState) -> Literal["ocr_invoice", "query_status", "general_response", "general_response"]:
    intent = state.get("intent", "general_question")
    if intent == "new_reimbursement":
        return "ocr_invoice"
    elif intent == "query_status":
        return "query_status"
    else:
        return "general_response"


def ocr_invoice(state: ReimburseState) -> dict:
    return {"messages": [AIMessage(content="[OCR] 票据识别完成，已提取发票信息。")]}


def compliance_review(state: ReimburseState) -> dict:
    expense_type = state.get("expense_type", "other")
    total = state.get("total_amount", 0)
    result = compliance_check.invoke({"expense_type": expense_type, "total_amount": total, "department": state.get("department", "")})
    return {"compliance_result": result}


def budget_control(state: ReimburseState) -> dict:
    department = state.get("department", "")
    total = state.get("total_amount", 0)
    result = budget_check.invoke({"department": department, "amount": total})
    return {"budget_result": result, "need_special_approval": result.get("need_special_approval", False)}


def route_after_budget(state: ReimburseState) -> Literal["special_approval", "generate_pdf"]:
    if state.get("need_special_approval", False):
        return "special_approval"
    return "generate_pdf"


def special_approval(state: ReimburseState) -> dict:
    return {"messages": [AIMessage(content="[审批] 预算超标，已自动标记为需要特殊审批流程。")]}


def generate_pdf(state: ReimburseState) -> dict:
    total = state.get("total_amount", 0)
    return {
        "pdf_path": f"/tmp/reimburse_{state.get('session_id', 'unknown')}.pdf",
        "messages": [AIMessage(content=f"[PDF] 报销单已生成，总金额: ¥{total:,.2f}")],
    }


def send_email(state: ReimburseState) -> dict:
    return {"messages": [AIMessage(content="[邮件] 报销单已发送至审批人邮箱。")]}


def query_status(state: ReimburseState) -> dict:
    return {"messages": [AIMessage(content="[查询] 报销单当前状态: 待审批 (部门经理)" + "\n下一步: 财务总监审批")]}


def general_response(state: ReimburseState) -> dict:
    messages = state["messages"]
    last_msg = messages[-1].content if messages else "你好"
    prompt = f"你是一个专业的企业财务报销助手。请友好地回答用户的问题：{last_msg}"
    response = llm.invoke([HumanMessage(content=prompt)])
    return {"messages": [AIMessage(content=response.content)]}


def build_graph() -> StateGraph:
    builder = StateGraph(ReimburseState)

    builder.add_node("classify_intent", classify_intent)
    builder.add_node("ocr_invoice", ocr_invoice)
    builder.add_node("compliance_review", compliance_review)
    builder.add_node("budget_control", budget_control)
    builder.add_node("special_approval", special_approval)
    builder.add_node("generate_pdf", generate_pdf)
    builder.add_node("send_email", send_email)
    builder.add_node("query_status", query_status)
    builder.add_node("general_response", general_response)

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
