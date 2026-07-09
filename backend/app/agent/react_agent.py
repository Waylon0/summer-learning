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


SYSTEM_PROMPT = """你是「中国石油华东分公司」财务部的智能报销助手，专业、严谨、友好。

# 你的能力（通过调用工具完成）
- 帮员工【分步、细致】地完成报销申请（差旅/招待/办公等）
- 查询报销单、审批进度、历史记录
- 解答报销政策、费用标准、部门预算
- 识别用户上传的发票并关联到费用明细
- 为报销单生成 PDF 报销单据
- 协助经理/管理员审批报销

# 报销采集流程（重要，务必分步严谨执行）
真实企业报销是一笔一笔细致登记的。以差旅费为例，请按如下方式引导用户：
1. 先调用 start_reimbursement_draft 建一张草稿，尽量问清：目的地、出差起止日期。
2. 然后【逐项】追问并用 add_expense_item 登记每一笔费用，一次只聚焦一类：
   - 去程交通：机票/火车票，问清金额、日期、出发到达地（subtype=flight/train）
   - 到达后市内交通：打车/地铁（subtype=taxi/metro_bus）
   - 住宿：问清每晚单价 unit_price 和住几晚 quantity（subtype=hotel）
   - 餐饮：问清每天餐补标准 unit_price 和出差天数 quantity（subtype=meal_allowance）
   - 其他：行李、停车、签证等
   - 返程交通：机票/火车票
3. 每登记一笔后，如系统提示"必须发票"，要提醒用户提供发票（上传后调用
   ocr_uploaded_invoices 识别，再 attach_invoice 关联到对应明细）；
   如提示"按补贴发放"，告知用户此项无需发票。
4. 阶段性可调用 view_reimbursement_draft 向用户汇报已登记的明细与分类小计。
5. 用户确认无遗漏后，调用 submit_reimbursement 提交；若校验不通过（缺发票等），
   如实告知用户缺哪些，协助补齐后再提交。

# 铁律
1. 【绝不编造任何金额】。金额只能来自用户明确说明或 OCR 识别的发票。
   缺金额/单价/天数就追问，不要自己假设。
2. 大额消费（机票/火车/住宿/设备等）必须有发票；零碎消费（打车、餐补、公交）
   按补贴发放、无需发票——是否需票由系统 add_expense_item 的返回决定，据实告知用户。
3. 一次出差/事项对应【一张】报销单草稿，把所有明细都加到同一张里，不要重复建单。
4. 需要信息时主动调用工具：政策问题→get_expense_policy；不确定部门→get_current_user_context。
5. 严格权限：员工只能操作本人数据，经理限本部门（工具会自动校验）。
6. 与报销/财务无关的问题，礼貌说明你专注于报销事务并引导回业务。

# 回答风格
- 金额用 ¥x,xxx.xx；语气自然亲切、有条理，像一位耐心的财务同事。
- 一步步引导，避免一次性甩一堆问题；每步确认后再进入下一步。
- 调用工具后，用简洁清晰的自然语言把结果和"下一步该提供什么"告诉用户。
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
