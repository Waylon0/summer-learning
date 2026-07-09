"""
=============================================================================
app/api/v1/conversations.py — 会话管理 API（类 DeepSeek 网页多会话）
=============================================================================
  POST   /conversations          新建会话（返回新的 session_id = conversation.id）
  GET    /conversations          列出当前用户的会话
  GET    /conversations/{id}     获取会话详情（含全部历史消息）
  PATCH  /conversations/{id}     重命名会话
  DELETE /conversations/{id}     删除会话

权限：均需登录，按 user_id 隔离，不能访问他人会话。
=============================================================================
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.conversation_svc import ConversationService
from app.schemas.conversation import (
    ConversationCreate, ConversationRename,
    ConversationSummary, ConversationDetail,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.post("", response_model=ConversationSummary)
async def create_conversation(
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """新建会话，返回其 id（即后续对话使用的 session_id）。"""
    svc = ConversationService(db)
    conv = await svc.create(user.id, data.title or "新对话")
    return ConversationSummary(**conv.to_dict())


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出当前用户的所有会话（按最近更新排序）。"""
    svc = ConversationService(db)
    convs = await svc.list_for_user(user.id)
    return [ConversationSummary(**c.to_dict()) for c in convs]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取会话详情及其全部历史消息（用于切换会话后恢复对话）。"""
    svc = ConversationService(db)
    conv = await svc.get_owned(conversation_id, user.id, with_messages=True)
    return ConversationDetail(**conv.to_dict(with_messages=True))


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: str,
    data: ConversationRename,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """重命名会话。"""
    svc = ConversationService(db)
    conv = await svc.rename(conversation_id, user.id, data.title)
    return ConversationSummary(**conv.to_dict())


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除会话及其全部消息。"""
    svc = ConversationService(db)
    await svc.delete(conversation_id, user.id)
    return {"id": conversation_id, "deleted": True}
