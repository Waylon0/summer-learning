import uuid
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from app.agent.graph import reimburse_graph
from app.schemas.reimbursement import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


@router.post("/chat")
async def chat(request: ChatRequest):
    """Agent 对话接口 — 支持流式响应 (SSE)"""
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
        raise HTTPException(status_code=500, detail=str(e))
