"""
=============================================================================
app/api/v1/chat.py — Agent 对话 API（上下文感知版）
=============================================================================
支持多轮对话：
  1. 每个请求携带 session_id，后端自动维护会话上下文
  2. 请求到达 → 加载历史上下文 → 注入到工作流 → 保存新上下文
  3. 上下文包括：消息历史、已提取实体、上一轮意图、缺失槽位

实现原理：
  - SessionStore 是内存级 KV 存储（session_id → 上下文）
  - 每次对话结束自动保存状态
  - 30 分钟无活动自动清理过期会话
=============================================================================
"""
import uuid
import json
import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage
from loguru import logger

from app.schemas.reimbursement import ChatRequest, ChatResponse
from app.core.exceptions import AgentExecutionError
from app.agent.sessions import get_session_store, SessionContext

router = APIRouter(tags=["chat"])


def _build_initial_state(request: ChatRequest, ctx: SessionContext, is_contextual: bool) -> dict:
    """
    构造 LangGraph 初始状态，注入上下文信息。

    与 v1.0 的区别：
      - 从 SessionContext 中恢复已提取的实体和意图
      - 将上下文摘要传给工作流，供意图分类器使用
    """
    session_id = request.session_id or ctx.session_id

    # 恢复历史消息（最近 6 条）
    history_messages = []
    for m in ctx.get_recent_messages(6):
        msg_cls = HumanMessage if m["role"] == "user" else AIMessage
        history_messages.append(msg_cls(content=m["content"]))
    # 当前消息放最后
    history_messages.append(HumanMessage(content=request.message))

    # 生成上下文摘要
    context_summary = ctx.get_context_summary() if ctx.turn_count > 0 else ""

    return {
        "messages": history_messages,
        "intent": ctx.last_intent if is_contextual else "",
        "sub_intent": ctx.last_sub_intent if is_contextual else "",
        "intent_result": {},
        "session_id": session_id,
        "department": ctx.department if is_contextual else "",
        "expense_type": ctx.expense_type if is_contextual else "",
        "total_amount": ctx.total_amount if is_contextual else 0.0,
        "description": ctx.description if is_contextual else "",
        "entities": {},
        "missing_slots": ctx.missing_slots if is_contextual else [],
        "is_contextual_fill": is_contextual,
        "context_summary": context_summary,
        "validation_result": {},
        "compliance_result": {},
        "budget_result": {},
        "need_special_approval": False,
        "invoices": [],
        "pdf_path": "",
        "status": "",
    }


def _save_context(session_id: str, result: dict, user_msg: str, reply: str):
    """保存对话上下文到会话仓库"""
    ctx = get_session_store().get_or_create(session_id)

    # 保存消息历史
    ctx.add_message("user", user_msg)
    ctx.add_message("assistant", reply)

    # 保存意图
    ctx.last_intent = result.get("intent", ctx.last_intent)
    ctx.last_sub_intent = result.get("sub_intent", ctx.last_sub_intent)

    # 保存实体（从 graph 结果中提取）
    ctx.update_entities(result.get("entities", {}))
    if result.get("department"):
        ctx.department = result["department"]
    if result.get("expense_type"):
        ctx.expense_type = result["expense_type"]
    if result.get("total_amount", 0) > 0:
        ctx.total_amount = result["total_amount"]

    # 如果本轮没有缺失槽位了（用户已补充完整），清除等待状态
    missing = result.get("missing_slots", [])
    if not missing and ctx.awaiting_response:
        ctx.awaiting_response = False
        ctx.missing_slots = []
        ctx.last_agent_question = ""

    get_session_store().save(ctx)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Agent 对话接口（上下文感知版）。

    多轮对话示例:
      User: "我要报销"
      Agent: "请问是哪个部门的？报销什么费用？大概多少金额？"
      User: "技术部，差旅费1500元"
      Agent: (识别为继续补充信息，提取部门+金额+类型) "✅ 票据识别完成..."
    """
    session_id = request.session_id or uuid.uuid4().hex
    t_start = time.perf_counter()

    # --- 步骤1：加载会话上下文 ---
    ctx = get_session_store().get_or_create(session_id)
    is_contextual = ctx.is_filling_slots()

    logger.info(
        f"Chat: session={session_id} turns={ctx.turn_count} "
        f"contextual={is_contextual} msg={request.message[:80]}"
    )

    # --- 步骤2：构造带上下文的工作流状态 ---
    initial_state = _build_initial_state(request, ctx, is_contextual)

    # --- 步骤3：执行工作流 ---
    try:
        from app.agent.graph import reimburse_graph
        result = reimburse_graph.invoke(initial_state)
        last_msg = result["messages"][-1].content if result["messages"] else "处理完成"
    except Exception as e:
        logger.error(f"Agent execution failed: {e}", exc_info=True)
        raise AgentExecutionError(detail=str(e))

    elapsed = (time.perf_counter() - t_start) * 1000
    logger.info(
        f"Chat done: intent={result.get('intent','?')} "
        f"reply_len={len(last_msg)} elapsed={elapsed:.0f}ms"
    )

    # --- 步骤4：保存上下文 ---
    _save_context(session_id, result, request.message, last_msg)

    return ChatResponse(
        reply=last_msg,
        session_id=session_id,
        intent=result.get("intent", ""),
        entities={
            "department": result.get("department", ""),
            "expense_type": result.get("expense_type", ""),
            "total_amount": result.get("total_amount", 0),
        },
    )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE 流式对话接口（上下文感知版）"""
    session_id = request.session_id or uuid.uuid4().hex
    ctx = get_session_store().get_or_create(session_id)
    is_contextual = ctx.is_filling_slots()
    initial_state = _build_initial_state(request, ctx, is_contextual)

    async def event_stream():
        try:
            from app.agent.graph import reimburse_graph
            result = reimburse_graph.invoke(initial_state)

            last_msg = result["messages"][-1].content if result["messages"] else ""
            _save_context(session_id, result, request.message, last_msg)

            yield f"data: {json.dumps({'type': 'intent', 'intent': result.get('intent', ''), 'session_id': session_id})}\n\n"

            for msg in result["messages"]:
                if hasattr(msg, "content") and msg.content:
                    yield f"data: {json.dumps({'type': 'message', 'content': msg.content})}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
