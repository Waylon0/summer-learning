"""
=============================================================================
app/api/v1/chat.py — Agent 对话 API（增强版）
=============================================================================
增强内容:
  - Agent 执行异常 → AgentExecutionError → 500 统一错误响应
  - 对话日志：记录每次请求的意图、耗时、回复长度
=============================================================================
"""
import uuid
import json
import time
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from loguru import logger

from app.schemas.reimbursement import ChatRequest, ChatResponse
from app.core.exceptions import AgentExecutionError

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Agent 对话接口"""
    session_id = request.session_id or uuid.uuid4().hex
    t_start = time.perf_counter()

    initial_state = {
        "messages": [HumanMessage(content=request.message)],
        "intent": "",
        "session_id": session_id,
        "department": "",
        "expense_type": "",
        "total_amount": 0.0,
        "invoices": [],
        "compliance_result": {},
        "budget_result": {},
        "need_special_approval": False,
        "pdf_path": "",
        "status": "",
    }

    try:
        from app.agent.graph import reimburse_graph
        result = reimburse_graph.invoke(initial_state)
        last_msg = result["messages"][-1].content if result["messages"] else "处理完成"

        elapsed = (time.perf_counter() - t_start) * 1000
        logger.info(
            f"对话完成: session={session_id} "
            f"intent={result.get('intent','?')} "
            f"reply_len={len(last_msg)} "
            f"elapsed={elapsed:.0f}ms"
        )

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
    except HTTPException:
        raise  # FastAPI 的 HTTPException 直接透传
    except Exception as e:
        logger.error(f"Agent execution failed: {e}", exc_info=True)
        raise AgentExecutionError(detail=str(e))


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """SSE 流式对话接口"""
    session_id = request.session_id or uuid.uuid4().hex

    initial_state = {
        "messages": [HumanMessage(content=request.message)],
        "intent": "",
        "session_id": session_id,
        "department": "",
        "expense_type": "",
        "total_amount": 0.0,
        "invoices": [],
        "compliance_result": {},
        "budget_result": {},
        "need_special_approval": False,
        "pdf_path": "",
        "status": "",
    }

    async def event_stream():
        try:
            from app.agent.graph import reimburse_graph
            result = reimburse_graph.invoke(initial_state)

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
