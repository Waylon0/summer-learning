"""
=============================================================================
app/api/v1/chat.py — Agent 对话 API（ReAct + 会话持久化 + 思考链流式）
=============================================================================
本次重构:
  - 会话由数据库 conversations 表管理，session_id = conversation.id，同一会话不变。
  - 上下文记忆不设限：把该会话【全部】历史消息喂给 LLM，尽量理解用户意图。
  - 语义理解完全交给 LLM（ReAct + function-calling），不再用规则/关键词。
  - RAG 知识库作为工具增强检索，不参与意图判断。
  - SSE 分类型推送 LLM 思考过程：
      start / thinking(token) / tool_call / tool_result / message / done / error
=============================================================================
"""
import json
import time

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from loguru import logger

from app.schemas.reimbursement import ChatRequest, ChatResponse
from app.core.exceptions import AgentExecutionError
from app.core.deps import get_current_user
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.services.conversation_svc import ConversationService
from app.agent.react_agent import get_agent, agent_available
from app.agent.agent_tools import set_agent_context

router = APIRouter(tags=["chat"])


# =============================================================================
# 辅助
# =============================================================================
def _sse_event(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _load_history_messages(conversation_id: str) -> list:
    """读取会话全部历史消息，转成 LangChain 消息列表（不设条数上限）。"""
    async with AsyncSessionLocal() as db:
        svc = ConversationService(db)
        rows = await svc.get_messages(conversation_id)
    msgs = []
    for m in rows:
        if m.role == "user":
            msgs.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            msgs.append(AIMessage(content=m.content))
    return msgs


async def _ensure_conversation(conversation_id: str | None, user: User) -> str:
    """校验会话归属；未提供则自动新建一个会话，返回 conversation_id。"""
    async with AsyncSessionLocal() as db:
        svc = ConversationService(db)
        if conversation_id:
            # 校验归属（不存在/越权 → 404）
            await svc.get_owned(conversation_id, user.id)
            return conversation_id
        conv = await svc.create(user.id, "新对话")
        return conv.id


async def _persist_turn(conversation_id: str, user_msg: str, reply: str, reasoning: list | None):
    async with AsyncSessionLocal() as db:
        svc = ConversationService(db)
        await svc.add_message(conversation_id, "user", user_msg)
        await svc.add_message(conversation_id, "assistant", reply, reasoning=reasoning)
        await svc.auto_title_if_needed(conversation_id, user_msg)


def _tool_label(name: str) -> str:
    """工具名 → 面向用户的中文描述（用于思考链展示）。"""
    return {
        "get_current_user_context": "获取当前用户信息",
        "get_expense_policy": "检索报销政策知识库",
        "get_department_budget": "查询部门预算",
        "check_expense_compliance": "校验费用合规性",
        "query_reimbursements": "查询报销单",
        "ocr_uploaded_invoices": "识别上传的发票",
        "submit_reimbursement": "提交报销申请",
        "generate_reimbursement_pdf_doc": "生成报销单PDF",
        "approve_reimbursement": "审批报销单",
    }.get(name, name)


def _extract_reimb_id_from_reasoning(reasoning: list[dict]) -> str | None:
    """从思考链工具结果中提取报销单 ID。"""
    for r in reasoning:
        if r.get("tool") == "save_reimbursement_to_db" and r.get("type") == "tool_result":
            out = r.get("output", "")
            try:
                if isinstance(out, str):
                    out = json.loads(out)
                if isinstance(out, dict) and "reimb_id" in out:
                    return out["reimb_id"]
            except (json.JSONDecodeError, TypeError):
                pass
    return None


# =============================================================================
# 非流式对话
# =============================================================================
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, req: Request, user: User = Depends(get_current_user)):
    """非流式对话（若客户端 Accept: text/event-stream 则转流式）。"""
    accept = req.headers.get("accept", "")
    if "text/event-stream" in accept:
        return await _chat_stream(request, user)

    if not agent_available():
        raise AgentExecutionError(detail="LLM 未配置，智能体不可用")

    conversation_id = await _ensure_conversation(request.session_id, user)
    history = await _load_history_messages(conversation_id)
    history.append(HumanMessage(content=request.message))

    set_agent_context(
        user_id=user.id, user_name=user.name, user_role=user.role,
        user_department=user.department, attachments=request.attachments or [],
    )

    try:
        result = await get_agent().ainvoke({"messages": history})
    except Exception as e:
        logger.error(f"Agent execution failed: {e}", exc_info=True)
        raise AgentExecutionError(detail=str(e))

    reply = ""
    for m in reversed(result.get("messages", [])):
        if isinstance(m, AIMessage) and m.content:
            reply = m.content if isinstance(m.content, str) else str(m.content)
            break

    await _persist_turn(conversation_id, request.message, reply, reasoning=None)
    return ChatResponse(reply=reply, session_id=conversation_id, intent="", entities={})


# =============================================================================
# 流式对话（SSE，含思考链）
# =============================================================================
@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, user: User = Depends(get_current_user)):
    return await _chat_stream(request, user)


async def _chat_stream(request: ChatRequest, user: User):
    if not agent_available():
        raise HTTPException(status_code=503, detail="LLM 未配置，智能体不可用")

    conversation_id = await _ensure_conversation(request.session_id, user)
    history = await _load_history_messages(conversation_id)
    history.append(HumanMessage(content=request.message))

    set_agent_context(
        user_id=user.id, user_name=user.name, user_role=user.role,
        user_department=user.department, attachments=request.attachments or [],
    )

    t_start = time.perf_counter()

    async def event_stream():
        reply_parts: list[str] = []
        reasoning: list[dict] = []   # 思考链（工具调用/结果）用于持久化
        try:
            yield _sse_event("start", {"session_id": conversation_id})

            agent = get_agent()
            async for ev in agent.astream_events({"messages": history}, version="v2"):
                etype = ev.get("event")
                name = ev.get("name", "")

                # 1) LLM 逐 token 输出 —— 作为"思考/回复"实时流
                if etype == "on_chat_model_stream":
                    chunk = ev.get("data", {}).get("chunk")
                    token = getattr(chunk, "content", "") if chunk else ""
                    if token:
                        reply_parts.append(token if isinstance(token, str) else str(token))
                        yield _sse_event("message", {"content": token})

                # 2) 工具开始调用 —— 展示"决定调用哪个工具"
                elif etype == "on_tool_start":
                    tool_input = ev.get("data", {}).get("input", {})
                    label = _tool_label(name)
                    reasoning.append({"type": "tool_call", "tool": name, "label": label, "input": tool_input})
                    yield _sse_event("tool_call", {
                        "tool": name, "label": label,
                        "input": tool_input,
                        "thought": f"我需要{label}",
                    })

                # 3) 工具返回结果
                elif etype == "on_tool_end":
                    output = ev.get("data", {}).get("output")
                    # ToolMessage or raw
                    out_content = getattr(output, "content", output)
                    try:
                        preview = out_content if isinstance(out_content, str) else json.dumps(out_content, ensure_ascii=False, default=str)
                    except Exception:
                        preview = str(out_content)
                    reasoning.append({"type": "tool_result", "tool": name, "label": _tool_label(name), "output": preview[:2000]})
                    yield _sse_event("tool_result", {
                        "tool": name, "label": _tool_label(name),
                        "output": preview[:2000],
                    })

            reply = "".join(reply_parts).strip()
            if not reply:
                reply = "抱歉，我暂时没能给出回复，请再说一次。"

            await _persist_turn(conversation_id, request.message, reply, reasoning=reasoning or None)

            # 从工具调用结果中提取报销单 ID（供前端"发送邮件"按钮使用）
            reimb_id = _extract_reimb_id_from_reasoning(reasoning)

            yield _sse_event("done", {
                "session_id": conversation_id,
                "elapsed_ms": round((time.perf_counter() - t_start) * 1000),
                "reimb_id": reimb_id,
            })
        except Exception as e:
            import traceback
            logger.error(f"Agent stream failed: {e}\n{traceback.format_exc()}")
            yield _sse_event("error", {"message": str(e), "type": type(e).__name__})
            yield _sse_event("done", {"session_id": conversation_id, "error": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
