"""
=============================================================================
app/agent/graph.py — 智能报销 Agent 工作流（LangGraph 状态机）
=============================================================================
这是整个项目的"AI 大脑"，使用 LangGraph 定义了报销审批的完整工作流。

工作流图示：
  START → classify_intent（意图分类）→
    ├─ new_reimbursement → ocr_invoice → compliance_review → budget_control →
    │    ├─ [预算超标] → special_approval → generate_pdf → send_email → END
    │    └─ [预算正常] → generate_pdf → send_email → END
    ├─ query_status → query_status → END
    └─ general_question → general_response → END

关键概念：
  - 节点（Node）：工作流中的一步操作（如"分类意图"、"检查预算"）
  - 边（Edge）：节点之间的连线（如"OCR完成后→进入合规审查"）
  - 条件边（Conditional Edge）：根据条件决定走哪条路（如"预算是否超标"）
  - 状态（State）：在整个流程中传递的数据（如用户消息、识别结果）

降级机制：
  如果 OpenAI API 不可用（没配 API Key 或网络不通），自动降级为"规则匹配模式"：
    用关键词识别意图（"报销"→新建，"查询"→查进度），不调用大模型。
=============================================================================
"""
import json
import re                                               # 正则表达式，用于从用户输入中提取金额
from typing import TypedDict, Annotated, Literal
from langgraph.graph import StateGraph, END             # StateGraph = 状态机蓝图，END = 结束标记
from langgraph.graph.message import add_messages        # 消息累加器（不会覆盖旧消息）
from langchain_core.messages import HumanMessage, AIMessage  # 对话消息类型
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

# =============================================================================
# LLM 懒加载 + 降级机制
# =============================================================================
# 如果 API Key 是默认的 "sk-xxx"，说明用户没配置，直接跳过 LLM 调用
_llm_available = False if "sk-xxx" in settings.OPENAI_API_KEY else None

llm = None  # 懒加载，真正需要时才创建


def _get_llm():
    """懒加载 LLM 客户端（第一次调用时才初始化，避免启动时因网络问题卡住）"""
    global llm
    if llm is None:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model=settings.OPENAI_MODEL,
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,         # 兼容国产大模型，改成他们的 API 地址即可
            temperature=0.1,                            # 温度越低回答越确定（0=完全确定，1=很有创意）
            request_timeout=5,                          # 5 秒超时，防止卡住
            max_retries=1,                              # 最多重试 1 次
        )
    return llm


def _try_llm(messages: list) -> str:
    """尝试调用 LLM，失败时静默降级为规则匹配"""
    global _llm_available
    if _llm_available is False:                         # 已知 LLM 不可用，直接返回空
        return ""
    try:
        resp = _get_llm().invoke(messages)
        _llm_available = True                           # 调用成功，标记可用
        return resp.content
    except Exception as e:
        if _llm_available is None:
            logger.warning(f"LLM unavailable, using rule-based fallback: {e}")
        _llm_available = False                          # 调用失败，标记不可用
        return ""


# =============================================================================
# 工作流状态定义
# =============================================================================
# 这是在整个工作流节点间传递的"数据包"。
# 每个节点函数接收 state，修改后返回需要更新的字段。
class ReimburseState(TypedDict):
    messages: Annotated[list, add_messages]              # 对话历史（add_messages 表示追加而不是覆盖）
    intent: str                                          # 识别的意图：new_reimbursement/query_status/general_question
    session_id: str                                      # 会话 ID（唯一标识一次对话）
    department: str                                      # 提取的部门名
    expense_type: str                                    # 费用类型
    total_amount: float                                  # 报销金额
    invoices: list[dict]                                 # 发票列表
    compliance_result: dict                              # 合规审查结果
    budget_result: dict                                  # 预算控制结果
    need_special_approval: bool                          # 是否需要特殊审批
    pdf_path: str                                        # 生成的 PDF 文件路径
    status: str                                          # 报销单状态


# =============================================================================
# 节点 1：意图分类（规则匹配版本）
# =============================================================================
def _rule_based_intent(text: str) -> dict:
    """
    用关键词规则识别用户意图（不需要大模型）：
      - 包含"报销/申请/差旅/招待/办公" → new_reimbursement
      - 包含"查询/进度/状态" → query_status
      - 其他 → general_question

    同时还提取：部门名、费用类型、金额。
    """
    text_lower = text.lower()

    # --- 意图识别 ---
    if any(w in text_lower for w in ["报销", "申请", "提交", "新建", "差旅", "招待", "办公"]):
        intent = "new_reimbursement"
    elif any(w in text_lower for w in ["查询", "进度", "状态", "审批"]):
        intent = "query_status"
    else:
        intent = "general_question"

    # --- 部门提取 ---
    dept = ""
    for d in ["技术部", "市场部", "财务部", "人事部", "研发部", "运营部"]:
        if d in text:
            dept = d
            break

    # --- 费用类型提取 ---
    expense = "other"
    if any(t in text_lower for t in ["差旅", "travel"]):
        expense = "travel"
    elif any(t in text_lower for t in ["招待", "entertainment"]):
        expense = "entertainment"
    elif any(t in text_lower for t in ["办公", "office"]):
        expense = "office"

    # --- 金额提取 ---
    # 正则匹配 "1500元" 或 "1500" 这样的数字
    nums = re.findall(r"(\d+(?:\.\d+)?)\s*元?", text)
    amount = float(nums[0]) if nums else 1500.0          # 没找到数字就用默认值

    return {"intent": intent, "department": dept, "expense_type": expense, "total_amount": amount}


def classify_intent(state: ReimburseState) -> dict:
    """
    意图分类节点：
      1. 先用规则匹配得到一个初始结果
      2. 如果 LLM 可用，再调用 LLM 修正（更准确）
      3. 去重后返回

    这是工作流的入口节点（set_entry_point）。
    """
    # 获取用户最后一条消息
    messages = state["messages"]
    last_msg = messages[-1].content if messages else ""

    # --- 步骤1：规则匹配 ---
    result = _rule_based_intent(last_msg)

    # --- 步骤2：LLM 修正（如果可用）---
    llm_response = _try_llm([
        HumanMessage(content=f"""你是一个意图分类器。只输出JSON。

意图: new_reimbursement(新建报销) / query_status(查询进度) / general_question

输入: {last_msg}

JSON:""")
    ])

    # --- 步骤3：合并 LLM 结果 ---
    if llm_response:
        content = llm_response.strip()
        # LLM 有时会返回 markdown 代码块格式，需要去掉 ```json ... ```
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
            pass  # LLM 返回了非法 JSON，忽略，用规则匹配结果

    logger.info(
        f"Intent: {result['intent']} | "
        f"Dept: {result['department']} | "
        f"Type: {result['expense_type']} | "
        f"¥{result['total_amount']}"
    )

    return {
        "intent": result["intent"],
        "department": result["department"],
        "expense_type": result["expense_type"],
        "total_amount": result["total_amount"],
    }


# =============================================================================
# 条件路由 1：根据意图选择下一步
# =============================================================================
def route_by_intent(state: ReimburseState) -> Literal["ocr_invoice", "query_status", "general_response"]:
    """意图 → 下一节点映射"""
    intent = state.get("intent", "general_question")
    if intent == "new_reimbursement":
        return "ocr_invoice"            # 新建报销 → 走 OCR 识别流程
    elif intent == "query_status":
        return "query_status"           # 查进度 → 直接查数据库
    return "general_response"           # 其他问题 → LLM 自由回答


# =============================================================================
# 节点 2：OCR 票据识别
# =============================================================================
def ocr_invoice(state: ReimburseState) -> dict:
    """
    模拟 OCR 识别发票信息。
    实际生产环境应调用 PaddleOCR 或大模型视觉能力读取真实发票图片。
    """
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


# =============================================================================
# 节点 3：合规审查
# =============================================================================
def compliance_review(state: ReimburseState) -> dict:
    """
    检查报销金额是否在公司规定标准内：
      - 差旅: 单次上限 ¥10,000，日标准 ¥500
      - 招待: 单次上限 ¥3,000，人均 ¥200
      - 办公: 单品上限 ¥5,000
      - 其他: 单次上限 ¥2,000
    """
    result = compliance_check(
        expense_type=state.get("expense_type", "other"),
        total_amount=state.get("total_amount", 0),
        department=state.get("department", ""),
    )
    logger.info(f"Compliance: {result}")
    return {"compliance_result": result}


# =============================================================================
# 节点 4：预算池控制
# =============================================================================
def budget_control(state: ReimburseState) -> dict:
    """
    查询部门预算余额，计算报销后是否超标。
    如果超标，设置 need_special_approval = True。
    """
    department = state.get("department", "")
    total = state.get("total_amount", 0)
    result = budget_check(department=department, amount=total)  # 查询真实数据库
    need = result.get("need_special_approval", False)
    logger.info(f"Budget: {department} amount={total} exceeded={need}")
    return {"budget_result": result, "need_special_approval": need}


# =============================================================================
# 条件路由 2：预算是否超标
# =============================================================================
def route_after_budget(state: ReimburseState) -> Literal["special_approval", "generate_pdf"]:
    """超标 → 特殊审批，正常 → 直接生成 PDF"""
    return "special_approval" if state.get("need_special_approval", False) else "generate_pdf"


# =============================================================================
# 节点 5a：特殊审批（预算超标时触发）
# =============================================================================
def special_approval(state: ReimburseState) -> dict:
    """标记为需要特殊审批，通知用户"""
    logger.warning("⚠️ Budget exceeded — special approval required")
    return {"messages": [AIMessage(
        content=(
            f"⚠️ 预算超标！该报销已标记为特殊审批流程。\n"
            f"部门: {state.get('department','')}\n"
            f"金额: ¥{state.get('total_amount',0):,.2f}"
        )
    )]}


# =============================================================================
# 节点 5：生成报销单 PDF
# =============================================================================
def generate_pdf(state: ReimburseState) -> dict:
    """调用 reportlab 生成真实 PDF 报销单"""
    total = state.get("total_amount", 0)
    path = generate_reimbursement_pdf(reimb_data={
        "id": state.get("session_id", "unknown"),
        "department": state.get("department", ""),
        "expense_type": state.get("expense_type", ""),
        "total_amount": total,
    })
    logger.info(f"PDF: {path}")
    return {
        "pdf_path": str(path),
        "messages": [AIMessage(content=f"📄 报销单已生成，总金额: ¥{total:,.2f}")],
    }


# =============================================================================
# 节点 6：发送审批邮件
# =============================================================================
def send_email(state: ReimburseState) -> dict:
    """通知用户：报销单已提交审批"""
    logger.info("📧 Sending email...")
    return {"messages": [AIMessage(
        content="📧 报销单已提交审批！\n"
                "审批流程: 部门经理 → 财务审核 → 出纳付款\n"
                "请前往「进度查询」追踪状态。"
    )]}


# =============================================================================
# 节点 B：查询审批进度
# =============================================================================
def query_status(state: ReimburseState) -> dict:
    """查询数据库中的审批流转记录，展示给用户"""
    result = query_reimbursement_status(reimb_id="", date_from="", date_to="")
    steps = result.get("steps", [])
    status_text = "\n".join(
        f"  {s['step']}. {s['approver']} — {s['action']}" for s in steps
    )
    return {"messages": [AIMessage(
        content=f"📋 报销单状态: {result.get('status','未知')}\n{status_text}"
    )]}


# =============================================================================
# 节点 C：通用回复
# =============================================================================
def general_response(state: ReimburseState) -> dict:
    """
    处理一般性问题（如"费用标准是什么"）。
    如果 LLM 可用 → 调用 LLM 回答
    如果不可用 → 返回预置的帮助信息
    """
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

    # LLM 不可用时的兜底回复
    return {"messages": [AIMessage(
        content=f"你好！我是财务报销助手。你可以这样使用我：\n\n"
                f"• 新建报销：\"我要报销差旅费 1500 元，部门技术部\"\n"
                f"• 查询进度：\"查询我的报销进度\"\n"
                f"• 政策咨询：\"差旅费标准是多少？\"\n\n"
                f"{system_prompt}"
    )]}


# =============================================================================
# 组装工作流
# =============================================================================
def build_graph():
    """
    用 LangGraph 搭建完整的工作流状态机。

    步骤：
      1. 创建 StateGraph 蓝图
      2. 注册所有节点（node）
      3. 设置入口节点
      4. 连接节点之间的边（edge）
      5. 设置条件分支（conditional_edges）
      6. 编译成可执行图
    """
    # --- 步骤1：创建蓝图 ---
    builder = StateGraph(ReimburseState)

    # --- 步骤2：注册 9 个节点 ---
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

    # --- 步骤3：设置入口（用户消息从哪个节点开始处理）---
    builder.set_entry_point("classify_intent")

    # --- 步骤4：意图分类后的条件分支 ---
    builder.add_conditional_edges("classify_intent", route_by_intent, {
        "ocr_invoice": "ocr_invoice",
        "query_status": "query_status",
        "general_response": "general_response",
    })

    # --- 步骤5：报销审批主链路 ---
    builder.add_edge("ocr_invoice", "compliance_review")       # OCR → 合规审查
    builder.add_edge("compliance_review", "budget_control")    # 合规 → 预算检查

    # --- 步骤6：预算检查后的条件分支 ---
    builder.add_conditional_edges("budget_control", route_after_budget, {
        "special_approval": "special_approval",
        "generate_pdf": "generate_pdf",
    })

    # --- 步骤7：末端链路 ---
    builder.add_edge("special_approval", "generate_pdf")       # 特殊审批 → 生成 PDF
    builder.add_edge("generate_pdf", "send_email")             # 生成 PDF → 发邮件
    builder.add_edge("send_email", END)                        # 发邮件 → 结束
    builder.add_edge("query_status", END)                      # 查询进度 → 结束
    builder.add_edge("general_response", END)                  # 通用回复 → 结束

    return builder.compile()


# =============================================================================
# 创建全局图实例
# =============================================================================
reimburse_graph = build_graph()
logger.info(
    f"LangGraph compiled ({len(reimburse_graph.nodes)} nodes, "
    f"LLM: {'online' if _llm_available else 'offline/rule-based'})"
)
