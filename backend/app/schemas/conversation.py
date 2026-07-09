"""
=============================================================================
app/schemas/conversation.py — 会话相关 Pydantic 模型
=============================================================================
"""
from pydantic import BaseModel, Field
from typing import Optional, Any


class ConversationCreate(BaseModel):
    title: Optional[str] = Field(default="新对话", description="会话标题")


class ConversationRename(BaseModel):
    title: str = Field(..., description="新的会话标题")


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ConversationMessageItem(BaseModel):
    id: str
    seq: int
    role: str
    content: str
    reasoning: Optional[Any] = None
    created_at: Optional[str] = None


class ConversationDetail(BaseModel):
    id: str
    title: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    messages: list[ConversationMessageItem] = []
