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
    DOCUMENT_PARSE = "document_parse"               # 票据识别
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
    PrimaryIntent.REIMBURSEMENT_QUERY: ["reimbursement_id"],  # 至少需要 ID 或日期范围
    PrimaryIntent.REIMBURSEMENT_MODIFY: ["reimbursement_id"],
    PrimaryIntent.POLICY_INQUIRY: [],
    PrimaryIntent.DOCUMENT_PARSE: ["file_path"],
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
    PrimaryIntent.REIMBURSEMENT_MODIFY: "modify_instance",
    PrimaryIntent.POLICY_INQUIRY: "policy_lookup",
    PrimaryIntent.DOCUMENT_PARSE: "ocr_invoice",
    PrimaryIntent.APPROVAL_ACTION: "approval_process",
    PrimaryIntent.GENERAL_CHAT: "general_response",
}


# =============================================================================
# 关键词 → 意图快速匹配表
# =============================================================================
_KEYWORD_INTENT_MAP = {
    # 新建报销
    "报销": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "申请": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "提交": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.NONE),
    "差旅": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.TRAVEL_EXPENSE),
    "出差": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.TRAVEL_EXPENSE),
    "机票": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.TRAVEL_EXPENSE),
    "酒店": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.TRAVEL_EXPENSE),
    "招待": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.ENTERTAINMENT_EXPENSE),
    "宴请": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.ENTERTAINMENT_EXPENSE),
    "请客": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.ENTERTAINMENT_EXPENSE),
    "办公": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.OFFICE_EXPENSE),
    "采购": (PrimaryIntent.REIMBURSEMENT_CREATE, SubIntent.OFFICE_EXPENSE),
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

    # 票据
    "发票": (PrimaryIntent.DOCUMENT_PARSE, SubIntent.NONE),
    "上传": (PrimaryIntent.DOCUMENT_PARSE, SubIntent.NONE),
    "票据": (PrimaryIntent.DOCUMENT_PARSE, SubIntent.NONE),
}


def classify_by_keywords(text: str) -> IntentResult:
    """
    基于关键词的快速意图分类。

    优先级规则（高→低）:
      1. 精确子意图关键词匹配（如 "差旅费" → travel_expense）
      2. 泛化一级意图匹配（如 "报销" → reimbursement_create）
      3. 兜底 → general_chat
    """
    text_lower = text.lower()
    best_match: IntentResult | None = None

    for keyword, (primary, sub) in _KEYWORD_INTENT_MAP.items():
        if keyword in text_lower:
            # 优先级：子意图 > 无子意图
            if best_match is None or sub != SubIntent.NONE:
                best_match = IntentResult(
                    primary=primary,
                    sub=sub if sub != SubIntent.NONE else SubIntent.NONE,
                    confidence=0.95 if sub != SubIntent.NONE else 0.85,
                    source="rule",
                )
            # 找到精确子意图就不继续了
            if best_match.sub != SubIntent.NONE and keyword in ["差旅", "出差", "招待", "宴请", "办公", "采购", "预支", "借款"]:
                break

    if best_match is None:
        # 没有任何关键词匹配 → 一般对话
        best_match = IntentResult(
            primary=PrimaryIntent.GENERAL_CHAT,
            sub=SubIntent.NONE,
            confidence=0.7,
            source="rule",
        )

    # 设置必需的实体槽位
    slots = INTENT_SLOTS_MAP.get(best_match.primary, [])
    sub_slots = SUB_INTENT_SLOTS_MAP.get(best_match.sub, [])
    best_match.required_slots = slots + sub_slots

    # 设置路由提示
    best_match.routing_hint = INTENT_ROUTING_MAP.get(best_match.primary, "general_response")

    return best_match


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
