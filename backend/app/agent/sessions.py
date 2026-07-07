"""
=============================================================================
app/agent/sessions.py — 会话状态管理（上下文记忆）
=============================================================================
实现多轮对话的"记忆力"，支持自动 Redis 持久化 + 内存降级：

  后端选择:
    - 优先 Redis (JSON 序列化, TTL 30min, 多实例共享)
    - 降级 Memory (单实例, 重启丢失)

  关键设计:
    - 会话过期时间：30 分钟无活动自动清理
    - 最大历史消息数：20 条（超出则保留最新的）
    - 上下文合并策略：新实体覆盖旧实体（最新信息优先）
=============================================================================
"""
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Optional
from loguru import logger


# =============================================================================
# 会话数据结构
# =============================================================================
@dataclass
class SessionContext:
    """单个会话的完整上下文"""
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    messages: list[dict] = field(default_factory=list)
    turn_count: int = 0
    last_intent: str = ""
    last_sub_intent: str = ""
    department: str = ""
    expense_type: str = ""
    total_amount: float = 0.0
    description: str = ""
    destination: str = ""
    guest_count: int = 0
    guest_company: str = ""
    missing_slots: list[str] = field(default_factory=list)
    awaiting_response: bool = False
    last_agent_question: str = ""
    user_id: str = ""

    # ---- JSON 序列化 ----
    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, data: str) -> "SessionContext":
        d = json.loads(data)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    # ---- 操作方法 ----
    def touch(self):
        self.last_activity = time.time()

    # 消息保留策略：存储至多 MAX_STORED 条，LLM 上下文取最近 MAX_CONTEXT 条
    MAX_STORED = 20   # 会话存储上限（防内存溢出）
    MAX_CONTEXT = 6    # 传给 LLM 的最近消息数（3轮对话，控 token 消耗）

    def add_message(self, role: str, content: str):
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > self.MAX_STORED:
            self.messages = self.messages[-self.MAX_STORED:]
        self.turn_count += 1
        self.touch()

    def get_recent_messages(self, n: int = None) -> list[dict]:
        """获取最近 N 条消息作为 LLM 上下文，默认 6 条（3 轮对话）"""
        if n is None:
            n = self.MAX_CONTEXT
        return self.messages[-n:]

    def get_context_summary(self) -> str:
        parts = [f"上一轮意图: {self.last_intent}"]
        if self.last_sub_intent and self.last_sub_intent != "none":
            parts[0] += f"({self.last_sub_intent})"
        confirmed = []
        for label, val in [("部门", self.department), ("类型", self.expense_type),
                           ("金额", self.total_amount), ("目的地", self.destination),
                           ("人数", self.guest_count)]:
            if val:
                confirmed.append(f"{label}={val}")
        if confirmed:
            parts.append("已确认: " + ", ".join(confirmed))
        if self.missing_slots:
            parts.append("等待补充: " + ", ".join(self.missing_slots))
        if self.last_agent_question:
            parts.append(f'Agent最后提问: "{self.last_agent_question}"')
        return "\n".join(parts)

    def update_entities(self, entities: dict):
        for field in ["department", "expense_type", "description",
                       "destination", "guest_company"]:
            if entities.get(field):
                setattr(self, field, entities[field])
        if entities.get("total_amount", 0) > 0:
            self.total_amount = entities["total_amount"]
        if entities.get("guest_count", 0) > 0:
            self.guest_count = entities["guest_count"]

    def is_filling_slots(self) -> bool:
        return self.awaiting_response and len(self.missing_slots) > 0


# =============================================================================
# Redis 后端（可选）
# =============================================================================
class RedisSessionBackend:
    """Redis 会话持久化后端（多实例共享）"""

    KEY_PREFIX = "reimburse:session:"
    TTL_SECONDS = 1800

    def __init__(self):
        self._redis = None

    def _get_redis(self):
        if self._redis is None:
            try:
                import redis as redis_lib
                from app.core.config import get_settings
                self._redis = redis_lib.from_url(
                    get_settings().REDIS_URL,
                    decode_responses=True,
                    socket_connect_timeout=2,
                )
                self._redis.ping()
                logger.info("SessionStore: Redis connected")
            except Exception as e:
                logger.warning(f"SessionStore: Redis unavailable ({e}), using memory fallback")
                self._redis = False
        return self._redis if self._redis is not False else None

    def get(self, session_id: str) -> SessionContext | None:
        r = self._get_redis()
        if not r:
            return None
        try:
            data = r.get(f"{self.KEY_PREFIX}{session_id}")
            return SessionContext.from_json(data) if data else None
        except Exception:
            return None

    def save(self, ctx: SessionContext) -> bool:
        r = self._get_redis()
        if not r:
            return False
        try:
            ctx.touch()
            r.setex(f"{self.KEY_PREFIX}{ctx.session_id}", self.TTL_SECONDS, ctx.to_json())
            return True
        except Exception:
            return False

    def delete(self, session_id: str):
        r = self._get_redis()
        if r:
            r.delete(f"{self.KEY_PREFIX}{session_id}")

    def exists(self, session_id: str) -> bool:
        r = self._get_redis()
        if not r:
            return False
        return bool(r.exists(f"{self.KEY_PREFIX}{session_id}"))


# =============================================================================
# 统一 SessionStore（Redis 优先 → 内存降级）
# =============================================================================
class SessionStore:
    """会话仓库，自动选择 Redis 或内存后端"""

    TTL_SECONDS = 1800

    def __init__(self):
        self._memory: dict[str, SessionContext] = {}
        self._redis = RedisSessionBackend()
        self._using_redis = self._redis.get("__ping__") is not None or True
        logger.info(
            f"SessionStore initialized (backend={'redis+memory' if self._redis._get_redis() else 'memory'}, TTL=30min)"
        )

    def get_or_create(self, session_id: str) -> SessionContext:
        # Try Redis first
        ctx = self._redis.get(session_id)
        if ctx:
            return ctx
        # Fallback to memory
        self._cleanup_memory()
        if session_id in self._memory:
            ctx = self._memory[session_id]
            ctx.touch()
            return ctx
        ctx = SessionContext(session_id=session_id)
        self._memory[session_id] = ctx
        return ctx

    def save(self, ctx: SessionContext):
        ctx.touch()
        self._redis.save(ctx)
        self._memory[ctx.session_id] = ctx

    def delete(self, session_id: str):
        self._redis.delete(session_id)
        self._memory.pop(session_id, None)

    def get_context(self, session_id: str) -> SessionContext | None:
        ctx = self._redis.get(session_id)
        return ctx or self._memory.get(session_id)

    def _cleanup_memory(self):
        now = time.time()
        expired = [sid for sid, c in self._memory.items() if now - c.last_activity > self.TTL_SECONDS]
        for sid in expired:
            del self._memory[sid]


# =============================================================================
# 全局单例 + 上下文推断
# =============================================================================
_session_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store


def infer_intent_from_context(current_text: str, ctx: SessionContext) -> dict | None:
    if not ctx.is_filling_slots():
        return None
    text_lower = current_text.lower().strip()
    confirm_words = ["是的", "对", "确认", "好的", "可以", "行", "没错", "嗯", "ok", "yes", "好"]
    if any(text_lower == w or text_lower.startswith(w) for w in confirm_words):
        return {"primary": ctx.last_intent, "sub": ctx.last_sub_intent, "confidence": 0.9, "contextual": True, "action": "confirm"}
    is_short = len(current_text) < 30
    has_slot = any(k in current_text for k in ["部", "元", "¥", "￥", "万", "千", "百", "差旅", "招待", "办公"])
    if is_short and has_slot:
        return {"primary": ctx.last_intent, "sub": ctx.last_sub_intent, "confidence": 0.85, "contextual": True, "action": "fill_slots"}
    if any(k in text_lower for k in ["查询", "进度", "状态", "标准", "政策", "流程"]):
        return None
    return None
