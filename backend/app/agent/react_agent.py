"""
=============================================================================
app/agent/react_agent.py — 基于 LangGraph 的 ReAct 报销智能体
=============================================================================
设计理念（本次重构）:
  - 不再用规则/关键词做意图理解；直接让 LLM 通过 ReAct + function-calling
    自主理解用户意图、自行决定调用哪些工具、如何多轮组合。
  - 不以节约 token 为目标：传入完整会话历史 + 完整工具集，让 LLM 充分发挥。
  - RAG 知识库仅作为「工具」增强检索（get_expense_policy），不参与意图判断。
  - 通过 astream_events 暴露 LLM 的思考/工具调用/结果，前端展示思考链。

依赖: langgraph.prebuilt.create_react_agent（自动实现 反思→调用工具→再反思 循环）
=============================================================================
"""
from __future__ import annotations

from loguru import logger
from langchain_core.messages import SystemMessage

from app.core.config import get_settings
from app.agent.agent_tools import AGENT_TOOLS

settings = get_settings()
_LLM_CONFIGURED = "sk-xxx" not in settings.OPENAI_API_KEY

_agent = None


SYSTEM_PROMPT = """你是「中国石油华东分公司」财务部的智能报销助手，专业、友好、可靠。

# 你的能力（通过调用工具完成）
- 帮员工提交报销申请（差旅/招待/办公/其他等）
- 查询报销单、审批进度、历史记录
- 解答报销政策、费用标准、部门预算
- 识别用户上传的发票并据此报销
- 为报销单生成 PDF 报销单据
- 协助经理/管理员审批报销

# 工作方式（重要）
1. 认真理解用户的真实意图，不要机械匹配关键词。
2. 需要信息时主动调用工具获取，不要凭空假设：
   - 不确定用户部门/身份 → 调用 get_current_user_context
   - 政策/标准/流程问题 → 调用 get_expense_policy 检索知识库后再回答
   - 用户上传了发票要报销 → 先调用 ocr_uploaded_invoices 拿到金额和明细
   - 查询报销 → 调用 query_reimbursements
3. 提交报销前必须确认「费用类型」和「金额」；缺少则向用户追问，
   【绝不允许自己编造金额】。金额只能来自：用户明确说明，或 OCR 识别的发票。
4. 只有在信息齐全并确认后，才调用 submit_reimbursement 真正提交。
5. 严格遵守权限：普通员工只能操作本人数据，经理限本部门，工具会自动校验。
6. 与报销/财务完全无关的问题，礼貌说明你专注于报销事务并引导用户回到业务。

# 回答风格
- 金额用 ¥x,xxx.xx 格式；语气自然亲切，像同事一样。
- 调用工具后，用简洁清晰的自然语言把结果转达给用户。
- 如果工具返回失败或权限不足，如实、委婉地告知原因。
"""


def _build_llm():
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=settings.OPENAI_MODEL,
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL,
        temperature=0.2,
        request_timeout=60,
        max_retries=2,
        streaming=True,
    )


def get_agent():
    """懒加载并缓存 ReAct agent。"""
    global _agent
    if _agent is None:
        from langgraph.prebuilt import create_react_agent
        _agent = create_react_agent(
            _build_llm(),
            tools=AGENT_TOOLS,
            prompt=SystemMessage(content=SYSTEM_PROMPT),
        )
        logger.info(f"ReAct agent compiled with {len(AGENT_TOOLS)} tools")
    return _agent


def agent_available() -> bool:
    return _LLM_CONFIGURED
