"""
=============================================================================
app/api/v1/chat.py — Agent 对话 API（SSE 流式）
=============================================================================
统一使用 SSE (Server-Sent Events) 流式输出，实时推送工作流的每一步进展。

Event 类型:
  start   — 对话开始（含 session_id）
  intent  — 意图识别结果
  step    — 工作流节点执行进度
  message — Agent 回复内容片段
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
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage
from loguru import logger

from app.schemas.reimbursement import ChatRequest
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


@router.post("/chat")
async def chat(request: ChatRequest):
    """
    SSE 流式对话接口。

    接入方式（JavaScript）:
      const es = new EventSource("/api/v1/chat", { method: "POST", body: ... });
      es.addEventListener("message", (e) => console.log(e.data));
      es.addEventListener("done", () => es.close());

    Event 流示例:
      event: start
      data: {"session_id":"abc123","timestamp":"..."}

      event: intent
      data: {"intent":"new_reimbursement","sub":"travel_expense","confidence":0.95}

      event: step
      data: {"node":"entity_extraction","status":"completed"}

      event: message
      data: {"content":"✅ 票据识别完成，已提取发票信息。"}

      event: result
      data: {"intent":"new_reimbursement","entities":{"department":"技术部",...}}

      event: done
      data: {"session_id":"abc123","elapsed_ms":2340}
    """
    session_id = request.session_id or uuid.uuid4().hex
    t_start = time.perf_counter()

    # --- 加载上下文 ---
    ctx = get_session_store().get_or_create(session_id)
    is_contextual = ctx.is_filling_slots()
    initial_state = _build_initial_state(request, ctx, is_contextual)

    logger.info(
        f"Chat: session={session_id} turns={ctx.turn_count} "
        f"contextual={is_contextual} msg={request.message[:80]}"
    )

    async def event_stream():
        try:
            # --- Event: start ---
            yield _sse_event("start", {
                "session_id": session_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })

            # --- 流式执行工作流：每个节点完成后立即推送 ---
            from app.agent.graph import reimburse_graph

            final_state = {}
            all_messages = set()

            async for chunk in reimburse_graph.astream(initial_state, stream_mode="updates"):
                # chunk 格式: {"node_name": {"messages": [...], "department": ..., ...}}
                for node_name, node_output in chunk.items():
                    # 推送节点名作为进度
                    if node_name:
                        yield _sse_event("step", {"node": node_name})

                    if isinstance(node_output, dict):
                        msgs = node_output.get("messages", [])
                        for msg in msgs:
                            if hasattr(msg, "content") and msg.content:
                                content = str(msg.content)
                                # 按字符逐个推送，实现打字机效果
                                # 用 hash 去重，避免重复推送
                                msg_hash = hash(content)
                                if msg_hash not in all_messages:
                                    all_messages.add(msg_hash)
                                    # 逐字符流式推送
                                    for i in range(0, len(content), 1):
                                        yield _sse_event("token", {
                                            "content": content[i],
                                            "node": node_name,
                                        })
                                    # 每条消息结束后发送换行
                                    yield _sse_event("token", {"content": "\n"})

                    # 累积最终状态
                    final_state.update(node_output)

            # --- 收集完整回复 ---
            last_msg = ""
            if final_state.get("messages"):
                for m in reversed(final_state["messages"]):
                    if hasattr(m, "content") and m.content:
                        last_msg = str(m.content)
                        break

            _save_context(session_id, final_state, request.message, last_msg)

            # --- Event: intent ---
            yield _sse_event("intent", {
                "intent": final_state.get("intent", ""),
                "sub_intent": final_state.get("sub_intent", ""),
            })

            # --- Event: result ---
            yield _sse_event("result", {
                "intent": final_state.get("intent", ""),
                "entities": {
                    "department": final_state.get("department", ""),
                    "expense_type": final_state.get("expense_type", ""),
                    "total_amount": final_state.get("total_amount", 0),
                },
                "reply_preview": last_msg[:200],
            })

            # --- Event: done ---
            elapsed = (time.perf_counter() - t_start) * 1000
            yield _sse_event("done", {
                "session_id": session_id,
                "elapsed_ms": round(elapsed, 0),
            })

        except Exception as e:
            logger.error(f"Agent execution failed: {e}", exc_info=True)
            yield _sse_event("error", {
                "error_code": "AGENT_ERROR",
                "message": str(e),
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
