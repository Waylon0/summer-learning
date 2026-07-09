"""
=============================================================================
app/agent/intents.py — 专业意图分类器（多级意图路由）
=============================================================================
区别于泛化 Agent 的简单分类，本模块实现企业报销领域的专业意图识别：

  一级意图（主路径）:
    - reimbursement_create  — 新建报销申请
    - reimbursement_query   — 报销进度/历史查询
    - reimbursement_modify  — 修改已有报销
    - policy_inquiry        — 政策/标准咨询
    - document_parse         — 票据/文件识别
    - approval_action        — 审批操作

  二级意图（子场景）:
    reimbursement_create:
      - single_invoice      — 单发票报销
      - multi_invoice       — 多发票汇总报销
      - travel_expense      — 差旅报销
      - entertainment_expense — 招待费报销
      - office_expense      — 办公费报销
      - advance_request     — 预支申请

    reimbursement_query:
      - status_check        — 审批进度查询
      - history_list        — 历史记录列表
      - amount_summary      — 金额汇总统计

    policy_inquiry:
      - expense_standard    — 费用标准查询
      - process_guide       — 报销流程指引
      - department_quota    — 部门额度查询

每个意图携带：
  - confidence   : 置信度 (0-1)
  - required_slots: 必需槽位（缺一不可，缺失时触发反问）
  - routing_hint : 路由提示（下一步应执行的节点）
=============================================================================
"""
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# 意图枚举定义
# =============================================================================
class PrimaryIntent(str, Enum):
    """一级意图（主路径）"""
    REIMBURSEMENT_CREATE = "reimbursement_create"  # 新建报销
    REIMBURSEMENT_QUERY = "reimbursement_query"    # 报销查询
    REIMBURSEMENT_MODIFY = "reimbursement_modify"  # 修改报销
    POLICY_INQUIRY = "policy_inquiry"              # 政策咨询
    DOCUMENT_PARSE = "document_parse"               # 票据识别（发票作为输入 OCR）
    REIMBURSEMENT_PDF = "reimbursement_pdf"         # 生成报销单 PDF（结构化单据）
    APPROVAL_ACTION = "approval_action"             # 审批操作
    GENERAL_CHAT = "general_chat"                   # 闲聊/其他


class SubIntent(str, Enum):
    """二级意图（细分场景）"""
    # 新建报销子类
    SINGLE_INVOICE = "single_invoice"
    MULTI_INVOICE = "multi_invoice"
    TRAVEL_EXPENSE = "travel_expense"
    ENTERTAINMENT_EXPENSE = "entertainment_expense"
    OFFICE_EXPENSE = "office_expense"
    ADVANCE_REQUEST = "advance_request"

    # 查询子类
    STATUS_CHECK = "status_check"
    HISTORY_LIST = "history_list"
    AMOUNT_SUMMARY = "amount_summary"

    # 政策咨询子类
    EXPENSE_STANDARD = "expense_standard"
    PROCESS_GUIDE = "process_guide"
    DEPARTMENT_QUOTA = "department_quota"

    # 其他
    NONE = "none"


# =============================================================================
# 意图分类结果数据结构
# =============================================================================
@dataclass
class IntentResult:
    """意图分类的完整输出"""
    primary: PrimaryIntent                                     # 一级意图
    sub: SubIntent = SubIntent.NONE                            # 二级意图（细分场景）
    confidence: float = 1.0                                    # 置信度 (0-1)，规则匹配为 1.0，LLM 返回实际值
    requires_llm: bool = False                                 # 是否需要 LLM 进一步确认

    # 实体槽位（必需项 → 缺一不可）
    required_slots: list[str] = field(default_factory=list)
    missing_slots: list[str] = field(default_factory=list)

    # 下一步路由
    routing_hint: str = ""

    # 来源标记
    source: str = "rule"                                       # rule | llm | hybrid

    def has_missing_slots(self) -> bool:
        """是否有缺失的必需槽位"""
        return len(self.missing_slots) > 0

    def to_dict(self) -> dict:
        return {
            "primary": self.primary.value,
            "sub": self.sub.value,
            "confidence": self.confidence,
            "requires_llm": self.requires_llm,
            "required_slots": self.required_slots,
            "missing_slots": self.missing_slots,
            "routing_hint": self.routing_hint,
            "source": self.source,
        }


# =============================================================================
# 意图 → 必需槽位映射表
# =============================================================================
INTENT_SLOTS_MAP: dict[PrimaryIntent, list[str]] = {
    PrimaryIntent.REIMBURSEMENT_CREATE: ["department", "expense_type", "total_amount"],
    PrimaryIntent.REIMBURSEMENT_QUERY: [],  # 不再强制要求 reimb_id — 支持"列出所有"、"查询我的报销"等无 ID 查询
    PrimaryIntent.REIMBURSEMENT_MODIFY: ["reimbursement_id"],
    PrimaryIntent.POLICY_INQUIRY: [],
    PrimaryIntent.DOCUMENT_PARSE: ["file_path"],
    PrimaryIntent.REIMBURSEMENT_PDF: [],  # 无强制槽位：可从上下文/报销单号获取
    PrimaryIntent.APPROVAL_ACTION: ["reimbursement_id", "action"],
    PrimaryIntent.GENERAL_CHAT: [],
}

# 子意图 → 额外必需槽位
# 注意: 日期类字段 (travel_dates, expected_date, expense_date) 不设为必需 —
#   用户不提供时不追问，Agent 继续执行后续流程
SUB_INTENT_SLOTS_MAP: dict[SubIntent, list[str]] = {
    SubIntent.TRAVEL_EXPENSE: ["destination"],
    SubIntent.ENTERTAINMENT_EXPENSE: ["guest_count", "guest_company"],
    SubIntent.ADVANCE_REQUEST: [],
    SubIntent.STATUS_CHECK: [],
    SubIntent.HISTORY_LIST: [],
    SubIntent.AMOUNT_SUMMARY: ["date_range"],
    SubIntent.EXPENSE_STANDARD: [],
    SubIntent.PROCESS_GUIDE: [],
    SubIntent.DEPARTMENT_QUOTA: ["department"],
    SubIntent.NONE: [],
    SubIntent.SINGLE_INVOICE: [],
    SubIntent.MULTI_INVOICE: [],
    SubIntent.OFFICE_EXPENSE: [],
}


# =============================================================================
# 路由映射：意图 → 下一节点
# =============================================================================
INTENT_ROUTING_MAP: dict[PrimaryIntent, str] = {
    PrimaryIntent.REIMBURSEMENT_CREATE: "entity_extraction",
    PrimaryIntent.REIMBURSEMENT_QUERY: "query_status",
    PrimaryIntent.REIMBURSEMENT_MODIFY: "modify_reimbursement",
    PrimaryIntent.POLICY_INQUIRY: "policy_lookup",
    PrimaryIntent.DOCUMENT_PARSE: "entity_extraction",
    PrimaryIntent.REIMBURSEMENT_PDF: "generate_reimbursement_doc",
    PrimaryIntent.APPROVAL_ACTION: "approval_process",
    PrimaryIntent.GENERAL_CHAT: "general_response",
}


# =============================================================================
# 关键词 → 意图快速匹配表
# =============================================================================
# 说明: 本表现由 app/agent/intent_registry.py 的注册表「自动生成」，
#       不再手工维护。新增意图/关键词请改注册表，避免多处硬编码漂移。
#       下方 _LEGACY_KEYWORD_INTENT_MAP 仅作历史保留（未使用）。
_LEGACY_KEYWORD_INTENT_MAP = {
    # 新建报销
    "报销": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "申请": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "提交": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    # 差旅
    "差旅": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.TRAVEL_EXPENSE),
    "出差": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.TRAVEL_EXPENSE),
    "机票": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.TRAVEL_EXPENSE),
    "酒店": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.TRAVEL_EXPENSE),
    # 招待
    "招待": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.ENTERTAINMENT_EXPENSE),
    "宴请": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.ENTERTAINMENT_EXPENSE),
    "请客": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.ENTERTAINMENT_EXPENSE),
    # 办公
    "办公": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.OFFICE_EXPENSE),
    "采购": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.OFFICE_EXPENSE),
    # 通信
    "通信": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "话费": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    # 会议
    "会议": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    # 培训
    "培训": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    # 部门专属
    "研发材料": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "研发设备": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "技术引进": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "软件许可": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "广告": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "展会": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "审计": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "招聘": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "装修": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "云服务": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    # 预支
    "预支": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.ADVANCE_REQUEST),
    "借款": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.ADVANCE_REQUEST),

    # 报销查询
    "查询": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.STATUS_CHECK),
    "进度": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.STATUS_CHECK),
    "状态": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.STATUS_CHECK),
    "审批": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.STATUS_CHECK),
    "历史": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.HISTORY_LIST),
    "汇总": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.AMOUNT_SUMMARY),
    "统计": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.AMOUNT_SUMMARY),
    # 列表/全部查询（无 ID 的泛化查询）
    "列出": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.HISTORY_LIST),
    "所有": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.HISTORY_LIST),
    "全部": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.HISTORY_LIST),
    "列表": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.HISTORY_LIST),
    "记录": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.HISTORY_LIST),
    "我的": (PrimaryIntent.REIMBURSEMENT_QUERY, SubIntent.HISTORY_LIST),

    # 修改报销
    "修改": (PrimaryIntent.REIMBURSEMENT_MODIFY, SubIntent.NONE),
    "撤回": (PrimaryIntent.REIMBURSEMENT_MODIFY, SubIntent.NONE),
    "更正": (PrimaryIntent.REIMBURSEMENT_MODIFY, SubIntent.NONE),

    # 政策咨询
    "标准": (PrimaryIntent.POLICY_INQUIRY, SubIntent.EXPENSE_STANDARD),
    "规定": (PrimaryIntent.POLICY_INQUIRY, SubIntent.EXPENSE_STANDARD),
    "额度": (PrimaryIntent.POLICY_INQUIRY, SubIntent.DEPARTMENT_QUOTA),
    "流程": (PrimaryIntent.POLICY_INQUIRY, SubIntent.PROCESS_GUIDE),
    "怎么报": (PrimaryIntent.POLICY_INQUIRY, SubIntent.PROCESS_GUIDE),
    "政策": (PrimaryIntent.POLICY_INQUIRY, SubIntent.EXPENSE_STANDARD),

    # 审批
    "通过": (PrimaryIntent.APPROVAL_ACTION, SubIntent.NONE),
    "驳回": (PrimaryIntent.APPROVAL_ACTION, SubIntent.NONE),
    "退回": (PrimaryIntent.APPROVAL_ACTION, SubIntent.NONE),
    "批准": (PrimaryIntent.APPROVAL_ACTION, SubIntent.NONE),
    "拒绝": (PrimaryIntent.APPROVAL_ACTION, SubIntent.NONE),

    # 票据识别（上传已有票据 → OCR）
    "发票": (PrimaryIntent.DOCUMENT_PARSE, SubIntent.NONE),
    "上传": (PrimaryIntent.DOCUMENT_PARSE, SubIntent.NONE),
    "票据": (PrimaryIntent.DOCUMENT_PARSE, SubIntent.NONE),

    # 票据生成（开具/生成新的发票 PDF）
    "生成报销单": (PrimaryIntent.REIMBURSEMENT_PDF, SubIntent.NONE),
    "报销单pdf": (PrimaryIntent.REIMBURSEMENT_PDF, SubIntent.NONE),
    "生成pdf": (PrimaryIntent.REIMBURSEMENT_PDF, SubIntent.NONE),
    "下载报销单": (PrimaryIntent.REIMBURSEMENT_PDF, SubIntent.NONE),
    "打印报销单": (PrimaryIntent.REIMBURSEMENT_PDF, SubIntent.NONE),
    "导出报销单": (PrimaryIntent.REIMBURSEMENT_PDF, SubIntent.NONE),
    "生成单据": (PrimaryIntent.REIMBURSEMENT_PDF, SubIntent.NONE),
}


def _fill_result(result: IntentResult) -> IntentResult:
    """补全 required_slots 与 routing_hint。"""
    slots = INTENT_SLOTS_MAP.get(result.primary, [])
    sub_slots = SUB_INTENT_SLOTS_MAP.get(result.sub, [])
    result.required_slots = slots + sub_slots
    result.routing_hint = INTENT_ROUTING_MAP.get(result.primary, "general_response")
    return result


def classify_by_keywords(text: str) -> IntentResult:
    """
    基于注册表的关键词打分分类（规则层）。

    评分规则（高→低）:
      1. priority_keywords 命中（复合短语，如"差旅费""生成发票"）→ 权重 10 + 词长
      2. keywords 命中（普通词，如"报销""办公"）→ 权重 3 + 词长
      3. 取总分最高的（子）意图；平局时优先「有子意图」的更具体项
      4. 无任何命中 → general_chat

    关键词/例句全部来自 intent_registry.INTENT_SPECS（单一事实来源），
    避免多处硬编码。
    """
    from app.agent.intent_registry import INTENT_SPECS

    text_lower = text.lower()
    best_spec = None
    best_score = 0.0

    for spec in INTENT_SPECS:
        score = 0.0
        # 优先短语：只计「最长命中」的一个，避免"差旅费"与"差旅"重复累加
        p_hits = [kw for kw in spec.priority_keywords if kw.lower() in text_lower]
        if p_hits:
            longest = max(p_hits, key=len)
            score += 10 + len(longest)
        # 普通关键词：同样只计最长命中一个
        k_hits = [kw for kw in spec.keywords if kw.lower() in text_lower]
        if k_hits:
            longest_k = max(k_hits, key=len)
            score += 3 + len(longest_k)
        if score <= 0:
            continue
        # 平局时：更具体的子意图（sub != NONE）优先
        more_specific = (
            best_spec is not None
            and score == best_score
            and spec.sub != SubIntent.NONE
            and best_spec.sub == SubIntent.NONE
        )
        if score > best_score or more_specific:
            best_score = score
            best_spec = spec

    if best_spec is None:
        return _fill_result(IntentResult(
            primary=PrimaryIntent.GENERAL_CHAT, sub=SubIntent.NONE,
            confidence=0.5, source="rule",
        ))

    # 置信度：命中复合短语给高分，仅普通词给中分
    confidence = 0.9 if best_score >= 10 else 0.8
    return _fill_result(IntentResult(
        primary=best_spec.primary, sub=best_spec.sub,
        confidence=confidence, source="rule",
    ))


def merge_with_llm(rule_result: IntentResult, llm_result: dict | None) -> IntentResult:
    """
    合并规则分类与 LLM 分类结果。

    策略：
      - LLM 结果权重更高（它能理解语义）
      - 但如果 LLM 返回空/不可用，保留规则结果
      - LLM 返回的置信度通常更高
    """
    if llm_result is None or not llm_result.get("primary"):
        rule_result.source = "rule"
        return rule_result

    # 尝试用 LLM 结果覆盖
    try:
        primary = PrimaryIntent(llm_result.get("primary", ""))
    except ValueError:
        primary = rule_result.primary

    try:
        sub = SubIntent(llm_result.get("sub", "none"))
    except ValueError:
        sub = rule_result.sub

    return IntentResult(
        primary=primary,
        sub=sub,
        confidence=float(llm_result.get("confidence", rule_result.confidence)),
        requires_llm=False,
        required_slots=INTENT_SLOTS_MAP.get(primary, []) + SUB_INTENT_SLOTS_MAP.get(sub, []),
        routing_hint=INTENT_ROUTING_MAP.get(primary, "general_response"),
        source="hybrid" if primary != rule_result.primary else "rule",
    )


def _result_from(primary: PrimaryIntent, sub: SubIntent, confidence: float, source: str) -> IntentResult:
    return _fill_result(IntentResult(
        primary=primary, sub=sub, confidence=confidence, source=source,
    ))


def fuse_intents(
    rule: IntentResult,
    semantic=None,           # semantic_router.RouteResult | None
    llm: dict | None = None,
    semantic_threshold: float = 0.72,
    semantic_margin: float = 0.06,
    llm_trust: float = 0.75,
) -> IntentResult:
    """
    三层意图融合（规则 + 语义向量 + LLM），提升自然语言理解准确率。

    决策优先级（综合置信度与一致性，而非简单谁覆盖谁）:
      1. LLM 高置信（≥ llm_trust）且输出合法 → 直接采纳 LLM（最强语义引擎）。
      2. LLM 与 语义路由「相互印证」（primary 一致）→ 采纳，置信度加成。
      3. LLM 与 规则「相互印证」→ 采纳。
      4. LLM 不可用时：语义路由分数高且区分度够（score≥阈值 且 margin 足）→ 采纳语义。
      5. 都不满足 → 回退规则结果（保底，永不崩）。

    这样：
      - 有 LLM 时以 LLM 为主，但用 规则/语义 交叉校验，降低单点误判。
      - 无 LLM（离线）时，语义路由兜底，仍优于纯关键词。
    """
    # 解析 LLM 输出为合法枚举
    llm_primary = llm_sub = None
    llm_conf = 0.0
    if llm and llm.get("primary"):
        try:
            llm_primary = PrimaryIntent(llm.get("primary", ""))
        except ValueError:
            llm_primary = None
        try:
            llm_sub = SubIntent(llm.get("sub") or "none")
        except ValueError:
            llm_sub = SubIntent.NONE
        try:
            llm_conf = float(llm.get("confidence", 0.8))
        except (TypeError, ValueError):
            llm_conf = 0.8

    sem_primary = semantic.primary if semantic else None
    sem_ok = bool(
        semantic
        and semantic.score >= semantic_threshold
        and semantic.margin >= semantic_margin
    )

    # 1) LLM 高置信直接采纳
    if llm_primary is not None and llm_conf >= llm_trust:
        return _result_from(llm_primary, llm_sub or SubIntent.NONE, llm_conf, "llm")

    # 2) LLM 与语义互证
    if llm_primary is not None and sem_primary == llm_primary:
        conf = min(0.99, max(llm_conf, semantic.score) + 0.1)
        # 子意图优先取更具体的
        sub = llm_sub if (llm_sub and llm_sub != SubIntent.NONE) else semantic.sub
        return _result_from(llm_primary, sub or SubIntent.NONE, conf, "llm+semantic")

    # 3) LLM 与规则互证
    if llm_primary is not None and llm_primary == rule.primary:
        sub = llm_sub if (llm_sub and llm_sub != SubIntent.NONE) else rule.sub
        return _result_from(llm_primary, sub or SubIntent.NONE, max(llm_conf, rule.confidence), "llm+rule")

    # 4) 有 LLM 但与其它层不一致：仍以 LLM 为准（它是最强语义），但降低置信度标记
    if llm_primary is not None:
        return _result_from(llm_primary, llm_sub or SubIntent.NONE, llm_conf, "llm")

    # ---- 以下为「无 LLM」离线路径 ----
    # 5) 规则高置信（命中复合短语，conf≥0.9）优先于「区分度不足」的语义结果。
    #    离线英文向量对中文区分力弱，容易高分误判，故强规则优先。
    strong_rule = rule.primary != PrimaryIntent.GENERAL_CHAT and rule.confidence >= 0.9
    if strong_rule and not (sem_primary == rule.primary):
        # 语义若明确且高区分度地指向别处，才考虑覆盖；否则信任强规则
        if not (sem_ok and semantic.margin >= 0.15):
            return rule

    # 6) 语义路由兜底（分数 + 区分度达标）
    if sem_ok:
        return _result_from(semantic.primary, semantic.sub, semantic.score, "semantic")

    # 7) 语义与规则一致时也可采纳（弱印证）
    if sem_primary is not None and sem_primary == rule.primary:
        return _result_from(rule.primary, rule.sub, max(rule.confidence, semantic.score), "rule+semantic")

    # 8) 最终回退规则
    return rule
