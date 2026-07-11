"""
=============================================================================
app/services/conversation_svc.py — 会话业务逻辑层
=============================================================================
提供会话的新建/列表/获取/重命名/删除，以及消息追加与历史读取。

设计要点:
  - 同一会话 id 即 session_id，贯穿始终；只有"新建会话"才产生新的 id。
  - 会话内消息不设条数上限（尽量让 LLM 理解完整上下文）。
  - 所有操作均按 user_id 隔离，杜绝越权访问他人会话。
=============================================================================
"""
import json
from datetime import datetime, timezone
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from loguru import logger

from app.models.conversation import Conversation, ConversationMessage
from app.core.exceptions import NotFoundException


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ 新建
    async def create(self, user_id: str, title: str = "新对话") -> Conversation:
        conv = Conversation(user_id=user_id, title=title or "新对话")
        self.db.add(conv)
        await self.db.commit()
        await self.db.refresh(conv)
        logger.info(f"会话已创建: {conv.id} user={user_id}")
        return conv

    # ------------------------------------------------------------------ 列表
    async def list_for_user(self, user_id: str, limit: int = 100) -> list[Conversation]:
        rows = await self.db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc())
            .limit(limit)
        )
        return list(rows.scalars().all())

    # ------------------------------------------------------------------ 获取
    async def get_owned(self, conversation_id: str, user_id: str, with_messages: bool = False) -> Conversation:
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        if with_messages:
            stmt = stmt.options(selectinload(Conversation.messages))
        conv = (await self.db.execute(stmt)).scalar_one_or_none()
        if not conv or conv.user_id != user_id:
            raise NotFoundException(resource="会话", identifier=conversation_id)
        return conv

    # ------------------------------------------------------------------ 重命名
    async def rename(self, conversation_id: str, user_id: str, title: str) -> Conversation:
        conv = await self.get_owned(conversation_id, user_id)
        conv.title = (title or "").strip()[:128] or conv.title
        await self.db.commit()
        await self.db.refresh(conv)
        return conv

    # ------------------------------------------------------------------ 删除
    async def delete(self, conversation_id: str, user_id: str) -> None:
        conv = await self.get_owned(conversation_id, user_id)
        await self.db.delete(conv)
        await self.db.commit()
        logger.info(f"会话已删除: {conversation_id} user={user_id}")

    # ------------------------------------------------------------ 历史消息
    async def get_messages(self, conversation_id: str) -> list[ConversationMessage]:
        rows = await self.db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.seq.asc())
        )
        return list(rows.scalars().all())

    # ------------------------------------------------------------ 追加消息
    async def add_message(
        self, conversation_id: str, role: str, content: str,
        reasoning: list | dict | None = None,
    ) -> ConversationMessage:
        # 计算下一个 seq
        max_seq = (await self.db.execute(
            select(func.coalesce(func.max(ConversationMessage.seq), 0))
            .where(ConversationMessage.conversation_id == conversation_id)
        )).scalar() or 0
        msg = ConversationMessage(
            conversation_id=conversation_id,
            seq=max_seq + 1,
            role=role,
            content=content or "",
            reasoning=json.dumps(reasoning, ensure_ascii=False) if reasoning else None,
        )
        self.db.add(msg)
        # 触发会话 updated_at 刷新
        conv = await self.db.get(Conversation, conversation_id)
        if conv is not None:
            # 用 Python 端时间而非 func.now() 表达式，避免属性被标记待刷新引发 MissingGreenlet
            conv.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(msg)
        return msg

    async def auto_title_if_needed(self, conversation_id: str, first_user_msg: str) -> None:
        """若会话仍是默认标题，用首条用户消息生成标题。"""
        conv = await self.db.get(Conversation, conversation_id)
        if conv and conv.title in ("新对话", "", None):
            conv.title = (first_user_msg or "新对话").strip()[:20]
            await self.db.commit()
