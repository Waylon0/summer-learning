"""
=============================================================================
app/models/conversation.py — 会话与消息 ORM 模型
=============================================================================
支持类 DeepSeek 网页的会话管理：
  - Conversation        : 一个会话（一个 session_id 贯穿始终）
  - ConversationMessage : 会话内的消息（user / assistant / tool 等）

设计:
  - conversation.id 即对话的 session_id，同一会话中始终不变。
  - 消息按 created_at 顺序持久化，会话上下文不设条数上限（尽量理解用户意图）。
=============================================================================
"""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, func, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Conversation(Base):
    """会话主表 —— 一个会话贯穿多轮对话，id 即 session_id。"""
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,
        default=lambda: uuid.uuid4().hex
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(128), nullable=False, default="新对话")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="ConversationMessage.seq",
    )

    def to_dict(self, with_messages: bool = False) -> dict:
        d = {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if with_messages:
            d["messages"] = [m.to_dict() for m in (self.messages or [])]
        return d


class ConversationMessage(Base):
    """会话消息表 —— 持久化每一条对话消息（含思考过程可选）。"""
    __tablename__ = "conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 会话内顺序
    role: Mapped[str] = mapped_column(String(16), nullable=False)         # user / assistant
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 可选：存储该轮的思考链/工具调用（JSON 字符串），便于回放
    reasoning: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    def to_dict(self) -> dict:
        import json as _json
        reasoning = None
        if self.reasoning:
            try:
                reasoning = _json.loads(self.reasoning)
            except (ValueError, TypeError):
                reasoning = None
        return {
            "id": self.id,
            "seq": self.seq,
            "role": self.role,
            "content": self.content,
            "reasoning": reasoning,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
