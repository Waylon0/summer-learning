"""
=============================================================================
app/api/v1/chat.py — Agent 对话 API
=============================================================================
提供两个端点：

  1. POST /api/v1/chat       — 普通对话（一次性返回全部结果）
  2. POST /api/v1/chat/stream — SSE 流式对话（实时推送，像 ChatGPT 逐字输出）

流程：
  前端发来用户消息 → 构造 LangGraph 初始状态 → 图执行 → 返回结果
=============================================================================
"""
import uuid
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse          # SSE（Server-Sent Events）响应
from langchain_core.messages import HumanMessage          # LangChain 的人类消息类型
from loguru import logger

from app.schemas.reimbursement import ChatRequest, ChatResponse

router = APIRouter(tags=["chat"])


# =============================================================================
# 端点 1：普通对话
# =============================================================================
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    普通对话接口 —— 一次性返回完整结果。

    请求示例：
      POST /api/v1/chat
      {"message": "我要报销差旅费1500元，部门技术部"}

    响应示例：
      {"reply": "📧 报销单已提交审批！", "session_id": "abc123", "intent": "new_reimbursement", ...}
    """
    # 生成或复用会话 ID（用于多轮对话追踪）
    session_id = request.session_id or uuid.uuid4().hex

    # ===== 构造 LangGraph 初始状态 =====
    # 这就是传给工作流第一个节点的"数据包"
    initial_state = {
        "messages": [HumanMessage(content=request.message)],  # 用户消息
        "intent": "",                                         # 待分类
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
        # 懒加载：真正需要时才导入（避免启动时的循环导入问题）
        from app.agent.graph import reimburse_graph
        # 执行工作流
        result = reimburse_graph.invoke(initial_state)

        # 取最后一条 AI 消息作为回复
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


# =============================================================================
# 端点 2：SSE 流式对话
# =============================================================================
@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    SSE 流式对话接口 —— 像 ChatGPT 一样实时推送消息。

    相比普通对话的区别：
      普通：等所有处理完成后一次性返回
      流式：处理过程中不断推送进度更新

    前端需使用 EventSource 或 fetch + ReadableStream 接收。
    """
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

    # ===== SSE 事件生成器 =====
    async def event_stream():
        """
        这是一个异步生成器函数。
        每次 yield 一行 SSE 格式的数据：
          data: {"type": "message", "content": "..."}

        SSE 格式要求：
          - 每条消息以 "data: " 开头
          - 以两个换行符 "\n\n" 结尾
        """
        try:
            logger.info(f"Stream chat: session={session_id} msg={request.message[:100]}")
            from app.agent.graph import reimburse_graph
            result = reimburse_graph.invoke(initial_state)

            # 推送意图识别结果
            yield f"data: {json.dumps({'type': 'intent', 'intent': result.get('intent', ''), 'session_id': session_id})}\n\n"

            # 逐条推送工作流中的消息
            for msg in result["messages"]:
                if hasattr(msg, "content") and msg.content:
                    yield f"data: {json.dumps({'type': 'message', 'content': msg.content})}\n\n"

            # 推送完成信号
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id})}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",                    # SSE 的 MIME 类型
        headers={
            "Cache-Control": "no-cache",                   # 不缓存
            "Connection": "keep-alive",                    # 保持连接
            "X-Accel-Buffering": "no",                    # Nginx 不缓冲
        },
    )
