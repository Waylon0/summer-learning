import uuid
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from loguru import logger

from app.schemas.reimbursement import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Agent 对话接口 — 非流式 (兼容前端)"""
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

    try:
        logger.info(f"Chat request: session={session_id} msg={request.message[:100]}")
        from app.agent.graph import reimburse_graph
        result = reimburse_graph.invoke(initial_state)
        last_msg = result["messages"][-1].content if result["messages"] else "处理完成"

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
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Agent 对话接口 — SSE 流式响应"""
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
            logger.info(f"Stream chat: session={session_id} msg={request.message[:100]}")
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
