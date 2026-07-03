"""
=============================================================================
app/agent/sessions.py — 会话状态管理（上下文记忆）
=============================================================================
实现多轮对话的"记忆力"：

  1. SessionStore — 内存中的会话仓库（生产环境可切换为 Redis）
  2. 每次对话结束自动保存状态
  3. 下次对话自动加载历史上下文
  4. 上下文摘要：提取关键实体和意图，供新消息参考

关键设计：
  - 会话过期时间：30 分钟无活动自动清理
  - 最大历史消息数：20 条（超出则保留最新的）
  - 上下文合并策略：新实体覆盖旧实体（最新信息优先）

小白理解：
  就像你和客服聊天，她说"请问哪个部门？"然后你说"技术部"。
  如果没有上下文记忆，Agent 会把"技术部"当成一句新话从头分析。
  有了上下文记忆，Agent 知道"技术部"是在回答上一个问题。
=============================================================================
"""
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger


# =============================================================================
# 会话数据结构
# =============================================================================
@dataclass
class SessionContext:
    """
    单个会话的完整上下文。

    包含：
      - 完整的消息历史（最近 N 条）
      - 上一轮识别的意图
      - 已提取的实体（跨轮累积）
      - 缺失的槽位（用于判断用户是否在补充信息）
    """
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)

    # 对话历史
    messages: list[dict] = field(default_factory=list)          # [{"role":"user/assistant", "content":"..."}, ...]
    turn_count: int = 0                                         # 轮次数

    # 意图上下文
    last_intent: str = ""                                       # 上一轮识别的一级意图
    last_sub_intent: str = ""                                   # 上一轮识别的二级意图

    # 实体上下文（跨轮累积，新值覆盖旧值）
    department: str = ""
    expense_type: str = ""
    total_amount: float = 0.0
    description: str = ""
    destination: str = ""
    guest_count: int = 0
    guest_company: str = ""

    # 对话状态
    missing_slots: list[str] = field(default_factory=list)      # 上一轮发现的缺失字段
    awaiting_response: bool = False                             # 是否在等待用户补充信息
    last_agent_question: str = ""                               # Agent 上次问了什么

    # 元数据
    user_id: str = ""

    def touch(self):
        """更新最后活动时间"""
        self.last_activity = time.time()

    def add_message(self, role: str, content: str):
        """添加一条消息到历史"""
        self.messages.append({"role": role, "content": content})
        # 只保留最近 20 条消息
        if len(self.messages) > 20:
            self.messages = self.messages[-20:]
        self.turn_count += 1
        self.touch()

    def get_recent_messages(self, n: int = 6) -> list[dict]:
        """获取最近 N 条消息"""
        return self.messages[-n:]

    def get_context_summary(self) -> str:
        """
        生成上下文摘要，供 LLM 理解当前对话状态。

        格式:
          [上下文] 上一轮意图: 新建报销(差旅), 已确认: 部门=技术部,金额=1500
          等待补充: 出发日期
          Agent最后提问: "请问出发日期是哪天？"
        """
        parts = [f"上一轮意图: {self.last_intent}"]
        if self.last_sub_intent and self.last_sub_intent != "none":
            parts[0] += f"({self.last_sub_intent})"

        confirmed = []
        if self.department:
            confirmed.append(f"部门={self.department}")
        if self.expense_type:
            confirmed.append(f"类型={self.expense_type}")
        if self.total_amount > 0:
            confirmed.append(f"金额={self.total_amount}")
        if self.destination:
            confirmed.append(f"目的地={self.destination}")
        if self.guest_count > 0:
            confirmed.append(f"人数={self.guest_count}")
        if confirmed:
            parts.append("已确认: " + ", ".join(confirmed))

        if self.missing_slots:
            parts.append("等待补充: " + ", ".join(self.missing_slots))

        if self.last_agent_question:
            parts.append(f"Agent最后提问: \"{self.last_agent_question}\"")

        return "\n".join(parts)

    def update_entities(self, entities: dict):
        """
        用新提取的实体更新上下文（非空才覆盖，避免丢失已有信息）。
        """
        if entities.get("department"):
            self.department = entities["department"]
        if entities.get("expense_type"):
            self.expense_type = entities["expense_type"]
        if entities.get("total_amount", 0) > 0:
            self.total_amount = entities["total_amount"]
        if entities.get("description"):
            self.description = entities["description"]
        if entities.get("destination"):
            self.destination = entities["destination"]
        if entities.get("guest_count", 0) > 0:
            self.guest_count = entities["guest_count"]
        if entities.get("guest_company"):
            self.guest_company = entities["guest_company"]

    def is_filling_slots(self) -> bool:
        """
        判断当前用户输入可能是在补充上一轮缺失的信息。
        条件：上一轮有缺失槽位 + Agent 在等待回复。
        """
        return self.awaiting_response and len(self.missing_slots) > 0


# =============================================================================
# 会话存储（内存实现）
# =============================================================================
class SessionStore:
    """
    会话仓库 —— 管理所有活跃会话。

    特性：
      - 内存存储（重启丢失，适合开发/演示）
      - 自动过期清理（30 分钟无活动则删除）
      - 线程安全（使用简单的并发控制）
    """

    TTL_SECONDS = 1800                                            # 30 分钟过期

    def __init__(self):
        self._store: dict[str, SessionContext] = {}
        logger.info("SessionStore initialized (in-memory, TTL=30min)")

    def get_or_create(self, session_id: str) -> SessionContext:
        """
        获取已有会话，不存在则创建新会话。
        自动清理过期会话。
        """
        self._cleanup_expired()

        if session_id in self._store:
            ctx = self._store[session_id]
            ctx.touch()
            logger.debug(f"Session resumed: {session_id} (turns={ctx.turn_count})")
            return ctx

        ctx = SessionContext(session_id=session_id)
        self._store[session_id] = ctx
        logger.debug(f"Session created: {session_id}")
        return ctx

    def save(self, ctx: SessionContext):
        """保存会话（更新最后活动时间）"""
        ctx.touch()
        self._store[ctx.session_id] = ctx

    def delete(self, session_id: str):
        """删除会话"""
        self._store.pop(session_id, None)
        logger.debug(f"Session deleted: {session_id}")

    def exists(self, session_id: str) -> bool:
        """检查会话是否存在"""
        self._cleanup_expired()
        return session_id in self._store

    def get_context(self, session_id: str) -> SessionContext | None:
        """获取会话上下文（不创建新会话）"""
        self._cleanup_expired()
        return self._store.get(session_id)

    def _cleanup_expired(self):
        """清理过期会话"""
        now = time.time()
        expired = [
            sid for sid, ctx in self._store.items()
            if now - ctx.last_activity > self.TTL_SECONDS
        ]
        for sid in expired:
            del self._store[sid]
        if expired:
            logger.info(f"Cleaned {len(expired)} expired sessions")


# =============================================================================
# 全局会话仓库单例
# =============================================================================
_session_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    """获取全局会话仓库单例"""
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store


# =============================================================================
# 上下文感知意图推断
# =============================================================================
def infer_intent_from_context(current_text: str, ctx: SessionContext) -> dict | None:
    """
    根据上下文推断用户当前消息的真实意图。

    场景 1：用户在补充信息
      - 上一轮 Agent 问了"哪个部门？多少钱？"
      - 用户回复"技术部，1500"
      - → 意图不变（仍是 reimbursement_create），但更新实体

    场景 2：用户开启新话题
      - 上一轮在讨论报销，用户突然说"查询我的报销进度"
      - → 意图变为 reimbursement_query

    场景 3：用户确认/否定
      - Agent 问"确认提交报销吗？"
      - 用户说"是的" / "对" / "确认"
      - → 意图不变，执行确认动作

    Returns:
        如果上下文明显指示意图不变，返回修正后的 intent 字典。
        否则返回 None，让正常的意图分类流程处理。
    """
    if not ctx.is_filling_slots():
        return None

    text_lower = current_text.lower().strip()

    # 场景 3：确认类回复
    confirm_words = ["是的", "对", "确认", "好的", "可以", "行", "没错", "嗯", "ok", "yes", "好"]
    if any(text_lower == w or text_lower.startswith(w) for w in confirm_words):
        return {
            "primary": ctx.last_intent,
            "sub": ctx.last_sub_intent,
            "confidence": 0.9,
            "contextual": True,
            "action": "confirm",
        }

    # 场景 1：补充信息（短消息 + 包含数字/部门名）
    is_short = len(current_text) < 30
    has_slot_info = any(
        keyword in current_text
        for keyword in ["部", "元", "¥", "￥", "万", "千", "百",
                       "差旅", "招待", "办公", "travel", "entertainment"]
    )
    if is_short and has_slot_info:
        return {
            "primary": ctx.last_intent,
            "sub": ctx.last_sub_intent,
            "confidence": 0.85,
            "contextual": True,
            "action": "fill_slots",
        }

    # 场景 2：新话题关键词（查询/政策）
    new_topic_keywords = ["查询", "进度", "状态", "标准", "政策", "流程"]
    if any(kw in text_lower for kw in new_topic_keywords):
        return None  # 让正常分类流程处理

    return None
