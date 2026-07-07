"""
=============================================================================
app/api/v1/chat.py — Agent 对话 API（非流式 + SSE 流式）
=============================================================================
两个端点:
  POST /api/v1/chat         — 非流式 JSON 响应（ChatResponse）
  POST /api/v1/chat/stream  — SSE 流式推送

Event 类型 (SSE):
  start   — 对话开始（含 session_id）
  intent  — 意图识别结果
  step    — 工作流节点执行进度
  message — Agent 回复内容片段
  token   — 逐字符流式推送
  result  — 完整结果摘要（intent + entities）
  done    — 对话完成
  error   — 异常信息

多轮对话支持:
  - 每个请求携带 session_id，后端自动维护上下文
  - 上下文包括消息历史、已提取实体、上一轮意图
=============================================================================
"""
import uuid
import json
import time
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from langchain_core.messages import HumanMessage, AIMessage
from loguru import logger

from app.schemas.reimbursement import ChatRequest, ChatResponse
from app.core.exceptions import AgentExecutionError
from app.agent.sessions import get_session_store, SessionContext

router = APIRouter(tags=["chat"])


def _build_initial_state(request: ChatRequest, ctx: SessionContext, is_contextual: bool) -> dict:
    """构造 LangGraph 初始状态，注入上下文信息"""
    session_id = request.session_id or ctx.session_id
    history_messages = []
    for m in ctx.get_recent_messages(6):
        msg_cls = HumanMessage if m["role"] == "user" else AIMessage
        history_messages.append(msg_cls(content=m["content"]))
    history_messages.append(HumanMessage(content=request.message))

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
        "reimb_id": "",
        "attachments": request.attachments or [],
    }


def _save_context(session_id: str, result: dict, user_msg: str, reply: str):
    """保存对话上下文到会话仓库"""
    ctx = get_session_store().get_or_create(session_id)
    ctx.add_message("user", user_msg)
    ctx.add_message("assistant", reply)
    ctx.last_intent = result.get("intent", ctx.last_intent)
    ctx.last_sub_intent = result.get("sub_intent", ctx.last_sub_intent)
    ctx.update_entities(result.get("entities", {}))
    if result.get("department"):
        ctx.department = result["department"]
    if result.get("expense_type"):
        ctx.expense_type = result["expense_type"]
    if result.get("total_amount", 0) > 0:
        ctx.total_amount = result["total_amount"]
    missing = result.get("missing_slots", [])
    if not missing and ctx.awaiting_response:
        ctx.awaiting_response = False
        ctx.missing_slots = []
        ctx.last_agent_question = ""
    get_session_store().save(ctx)


def _sse_event(event_type: str, data: dict) -> str:
    """格式化一条 SSE 事件"""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_workflow(initial_state: dict) -> dict:
    """执行 LangGraph 工作流，收集最终状态"""
    from app.agent.graph import reimburse_graph

    final_state = {}
    async for chunk in reimburse_graph.astream(initial_state, stream_mode="updates"):
        for _node_name, node_output in chunk.items():
            if isinstance(node_output, dict):
                final_state.update(node_output)
    return final_state


def _collect_reply(final_state: dict) -> str:
    """从最终状态中提取回复文本"""
    if final_state.get("messages"):
        for m in reversed(final_state["messages"]):
            if hasattr(m, "content") and m.content:
                return str(m.content)
    return ""


# =============================================================================
# POST /api/v1/chat — 非流式 JSON 响应
# =============================================================================
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request):
    """
    非流式对话接口，返回完整 ChatResponse。

    响应格式:
      {
        "reply": "✅ 报销单已创建 (单号: abc123)",
        "session_id": "abc123",
        "intent": "reimbursement_create",
        "entities": {"department": "技术部", "expense_type": "travel", "total_amount": 1500.0},
        "tool_calls": null
      }

    如果前端需要 SSE 流式，请使用 POST /api/v1/chat/stream
    """
    accept = req.headers.get("accept", "")
    if "text/event-stream" in accept:
        return await _chat_stream(request)

    session_id = request.session_id or uuid.uuid4().hex
    t_start = time.perf_counter()

    ctx = get_session_store().get_or_create(session_id)
    is_contextual = ctx.is_filling_slots()
    initial_state = _build_initial_state(request, ctx, is_contextual)

    logger.info(
        f"Chat(non-stream): session={session_id} turns={ctx.turn_count} "
        f"contextual={is_contextual} msg={request.message[:80]}"
    )

    try:
        final_state = await _run_workflow(initial_state)
    except Exception as e:
        logger.error(f"Agent execution failed: {e}", exc_info=True)
        raise AgentExecutionError(detail=str(e))

    reply = _collect_reply(final_state)
    _save_context(session_id, final_state, request.message, reply)

    elapsed_ms = round((time.perf_counter() - t_start) * 1000)
    logger.info(f"Chat done: session={session_id} elapsed={elapsed_ms}ms")

    return ChatResponse(
        reply=reply,
        session_id=session_id,
        intent=final_state.get("intent", ""),
        entities={
            "department": final_state.get("department", ""),
            "expense_type": final_state.get("expense_type", ""),
            "total_amount": final_state.get("total_amount", 0),
        },
    )


# =============================================================================
# POST /api/v1/chat/stream — SSE 流式推送
# =============================================================================
@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE 流式对话接口（POST /api/v1/chat/stream）"""
    return await _chat_stream(request)


async def _chat_stream(request: ChatRequest):
    """
    SSE 流式对话核心逻辑。

    Event 流示例:
      event: start
      data: {"session_id":"abc123","timestamp":"..."}

      event: step
      data: {"node":"classify_intent"}

      event: token
      data: {"content":"✅","node":"save_to_db"}

      event: intent
      data: {"intent":"reimbursement_create","sub_intent":"travel_expense"}

      event: result
      data: {"intent":"reimbursement_create","entities":{...},"reply_preview":"..."}

      event: done
      data: {"session_id":"abc123","elapsed_ms":2340}
    """
    session_id = request.session_id or uuid.uuid4().hex
    t_start = time.perf_counter()

    ctx = get_session_store().get_or_create(session_id)
    is_contextual = ctx.is_filling_slots()
    initial_state = _build_initial_state(request, ctx, is_contextual)

    logger.info(
        f"Chat(stream): session={session_id} turns={ctx.turn_count} "
        f"contextual={is_contextual} msg={request.message[:80]}"
    )

    async def event_stream():
        try:
            yield _sse_event("start", {
                "session_id": session_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })

            from app.agent.graph import reimburse_graph

            final_state = {}
            all_messages = set()

            async for chunk in reimburse_graph.astream(initial_state, stream_mode="updates"):
                for node_name, node_output in chunk.items():
                    if node_name:
                        yield _sse_event("step", {"node": node_name})

                    if isinstance(node_output, dict):
                        msgs = node_output.get("messages", [])
                        for msg in msgs:
                            if hasattr(msg, "content") and msg.content:
                                content = str(msg.content)
                                msg_hash = hash(content)
                                if msg_hash not in all_messages:
                                    all_messages.add(msg_hash)
                                    yield _sse_event("message", {
                                        "content": content,
                                        "node": node_name,
                                    })
                        final_state.update(node_output)

            reply = _collect_reply(final_state)
            _save_context(session_id, final_state, request.message, reply)

            yield _sse_event("intent", {
                "intent": final_state.get("intent", ""),
                "sub_intent": final_state.get("sub_intent", ""),
            })

            yield _sse_event("result", {
                "intent": final_state.get("intent", ""),
                "entities": {
                    "department": final_state.get("department", ""),
                    "expense_type": final_state.get("expense_type", ""),
                    "total_amount": final_state.get("total_amount", 0),
                },
                "reply_preview": reply[:200],
            })

            elapsed = (time.perf_counter() - t_start) * 1000
            yield _sse_event("done", {
                "session_id": session_id,
                "elapsed_ms": round(elapsed, 0),
            })

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"Agent execution failed: {e}\n{tb}")
            # Send descriptive error to frontend
            yield _sse_event("error", {
                "error_code": "AGENT_ERROR",
                "message": str(e),
                "type": type(e).__name__,
                "suggestion": "请稍后重试，或提供更完整的信息（部门、金额、费用类型）。",
            })
            # Also send done event so frontend stream ends cleanly
            elapsed = (time.perf_counter() - t_start) * 1000
            yield _sse_event("done", {
                "session_id": session_id,
                "elapsed_ms": round(elapsed, 0),
                "error": str(e),
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
