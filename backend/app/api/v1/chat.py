"""
=============================================================================
app/api/v1/chat.py — Agent 对话 API（非流式 + SSE 流式）
=============================================================================
支持可选 JWT 认证：登录用户自动关联部门/姓名，未登录用户使用默认值。
=============================================================================
"""
import uuid
import json
import time
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage
from loguru import logger

from app.schemas.reimbursement import ChatRequest, ChatResponse
from app.core.exceptions import AgentExecutionError
from app.core.deps import get_optional_user
from app.models.user import User
from app.agent.sessions import get_session_store, SessionContext

router = APIRouter(tags=["chat"])


def _build_initial_state(request: ChatRequest, ctx: SessionContext, is_contextual: bool, user: User | None = None) -> dict:
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
        # JWT 用户默认部门（始终以 JWT 为准，后续由 entity_extraction 三层层级回退）
        "department": ctx.department or (user.department if user else ""),
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
        "user_id": user.id if user else "",
        "user_name": user.name if user else "",
        "user_role": user.role if user else "",
        "user_department": user.department if user else "",
    }


def _save_context(session_id: str, result: dict, user_msg: str, reply: str):
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

    # 记住本轮仍缺失的必要槽位：下一轮用户的回复将被视为对这些槽位的补充。
    missing = result.get("missing_slots", [])
    if missing:
        # Agent 主动追问了缺失信息 → 进入"等待补充"状态
        ctx.missing_slots = missing
        ctx.awaiting_response = True
        ctx.last_agent_question = reply
    elif ctx.awaiting_response:
        # 槽位已补全 → 退出"等待补充"状态
        ctx.awaiting_response = False
        ctx.missing_slots = []
        ctx.last_agent_question = ""
    get_session_store().save(ctx)


def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _run_workflow(initial_state: dict) -> dict:
    from app.agent.graph import reimburse_graph
    final_state = {}
    async for chunk in reimburse_graph.astream(initial_state, stream_mode="updates"):
        for _node_name, node_output in chunk.items():
            if isinstance(node_output, dict):
                final_state.update(node_output)
    return final_state


def _collect_reply(final_state: dict) -> str:
    if final_state.get("messages"):
        for m in reversed(final_state["messages"]):
            if hasattr(m, "content") and m.content:
                return str(m.content)
    return ""


# =============================================================================
# POST /api/v1/chat — 非流式 JSON 响应
# =============================================================================
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request, user: User | None = Depends(get_optional_user)):
    """非流式对话接口"""
    accept = req.headers.get("accept", "")
    if "text/event-stream" in accept:
        return await _chat_stream(request, user)

    session_id = request.session_id or uuid.uuid4().hex
    t_start = time.perf_counter()
    ctx = get_session_store().get_or_create(session_id)
    is_contextual = ctx.is_filling_slots()
    initial_state = _build_initial_state(request, ctx, is_contextual, user)

    logger.info(f"Chat(non-stream): user={user.username if user else 'anon'} session={session_id} turns={ctx.turn_count} msg={request.message[:80]}")

    try:
        final_state = await _run_workflow(initial_state)
    except Exception as e:
        logger.error(f"Agent execution failed: {e}", exc_info=True)
        raise AgentExecutionError(detail=str(e))

    reply = _collect_reply(final_state)
    _save_context(session_id, final_state, request.message, reply)

    return ChatResponse(
        reply=reply, session_id=session_id,
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
async def chat_stream(request: ChatRequest, user: User | None = Depends(get_optional_user)):
    """SSE 流式对话接口"""
    return await _chat_stream(request, user)


async def _chat_stream(request: ChatRequest, user: User | None = None):
    session_id = request.session_id or uuid.uuid4().hex
    t_start = time.perf_counter()
    ctx = get_session_store().get_or_create(session_id)
    is_contextual = ctx.is_filling_slots()
    initial_state = _build_initial_state(request, ctx, is_contextual, user)

    logger.info(f"Chat(stream): user={user.username if user else 'anon'} session={session_id} turns={ctx.turn_count} msg={request.message[:80]}")

    async def event_stream():
        try:
            yield _sse_event("start", {"session_id": session_id, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")})
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
                                    yield _sse_event("message", {"content": content, "node": node_name})
                        final_state.update(node_output)

            reply = _collect_reply(final_state)
            _save_context(session_id, final_state, request.message, reply)

            yield _sse_event("intent", {"intent": final_state.get("intent", ""), "sub_intent": final_state.get("sub_intent", "")})
            yield _sse_event("result", {"intent": final_state.get("intent", ""), "entities": {"department": final_state.get("department", ""), "expense_type": final_state.get("expense_type", ""), "total_amount": final_state.get("total_amount", 0)}, "reply_preview": reply[:200]})
            yield _sse_event("done", {"session_id": session_id, "elapsed_ms": round((time.perf_counter() - t_start) * 1000)})
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error(f"Agent execution failed: {e}\n{tb}")
            yield _sse_event("error", {"error_code": "AGENT_ERROR", "message": str(e), "type": type(e).__name__, "suggestion": "请稍后重试，或提供更完整的信息"})
            yield _sse_event("done", {"session_id": session_id, "elapsed_ms": round((time.perf_counter() - t_start) * 1000), "error": str(e)})

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})
