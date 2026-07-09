"""
=============================================================================
app/agent/expense_rules.py — 企业报销费用分类与政策规则
=============================================================================
从真实企业角度定义细颗粒度的费用分类、发票门槛、补贴规则、每类校验标准。

核心概念:
  - 费用大类 category（如 transport 交通、accommodation 住宿、meal 餐饮）
  - 费用子类 subtype（如 flight 机票、train 火车、taxi 打车）
  - 单据要求 evidence:
        required   = 必须提供发票（大额交易，如机票/火车/住宿）
        subsidy    = 以补贴/津贴形式发放，无需发票（如打车、餐补）
        conditional= 超过某金额门槛才需发票
=============================================================================
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


# 单据要求类型
EVIDENCE_REQUIRED = "required"       # 必须发票
EVIDENCE_SUBSIDY = "subsidy"         # 补贴形式，无需发票
EVIDENCE_CONDITIONAL = "conditional" # 超门槛需发票


@dataclass
class SubtypeRule:
    """单个费用子类的规则。"""
    code: str                        # 子类代码，如 flight
    label: str                       # 中文名，如 机票
    category: str                    # 所属大类
    evidence: str                    # required / subsidy / conditional
    invoice_threshold: float = 0.0   # conditional 时：超过此额需发票
    per_unit_limit: float = 0.0      # 单笔/单日上限（0=不限）
    unit: str = ""                   # 计量单位（如 元/晚、元/天）
    note: str = ""                   # 说明


# =============================================================================
# 费用大类
# =============================================================================
CATEGORY_LABELS = {
    "transport_intercity": "城际交通费",   # 机票/火车/长途大巴（往返出差地）
    "transport_local": "市内交通费",       # 出差地打车/公交/地铁
    "accommodation": "住宿费",
    "meal": "餐饮费",
    "other_travel": "其他差旅费",          # 行李、签证、保险等
    "entertainment": "业务招待费",
    "office": "办公费",
    "communication": "通信费",
    "training": "培训费",
    "other": "其他费用",
}


# =============================================================================
# 费用子类规则表
# =============================================================================
SUBTYPE_RULES: dict[str, SubtypeRule] = {
    # ---- 城际交通（大额，必须发票）----
    "flight": SubtypeRule("flight", "机票", "transport_intercity", EVIDENCE_REQUIRED,
                          per_unit_limit=0, unit="元/程", note="经济舱，需登机牌或行程单"),
    "train": SubtypeRule("train", "火车票", "transport_intercity", EVIDENCE_REQUIRED,
                         unit="元/程", note="高铁二等座/动车，需车票"),
    "coach": SubtypeRule("coach", "长途汽车", "transport_intercity", EVIDENCE_REQUIRED,
                         unit="元/程", note="需车票"),
    "intercity_other": SubtypeRule("intercity_other", "其他城际交通", "transport_intercity",
                                   EVIDENCE_CONDITIONAL, invoice_threshold=100, unit="元/程"),

    # ---- 市内交通（零碎，补贴为主）----
    "taxi": SubtypeRule("taxi", "出租车/网约车", "transport_local", EVIDENCE_CONDITIONAL,
                        invoice_threshold=100, unit="元/次", note="单次≥100元需发票，否则按补贴"),
    "metro_bus": SubtypeRule("metro_bus", "地铁/公交", "transport_local", EVIDENCE_SUBSIDY,
                             unit="元/次", note="按补贴发放，无需发票"),
    "parking": SubtypeRule("parking", "停车费", "transport_local", EVIDENCE_CONDITIONAL,
                           invoice_threshold=100, unit="元"),
    "fuel": SubtypeRule("fuel", "油费", "transport_local", EVIDENCE_REQUIRED, unit="元"),

    # ---- 住宿（大额，必须发票，有日限）----
    "hotel": SubtypeRule("hotel", "酒店住宿", "accommodation", EVIDENCE_REQUIRED,
                         per_unit_limit=500, unit="元/晚",
                         note="一线城市≤500元/晚，需住宿发票"),

    # ---- 餐饮（补贴为主，有日限）----
    "meal_allowance": SubtypeRule("meal_allowance", "餐饮补贴", "meal", EVIDENCE_SUBSIDY,
                                  per_unit_limit=150, unit="元/天",
                                  note="出差期间每人每天≤150元，按补贴发放，无需逐餐发票"),
    "business_meal": SubtypeRule("business_meal", "商务用餐", "meal", EVIDENCE_REQUIRED,
                                 unit="元/次", note="正式商务宴请，需发票"),

    # ---- 其他差旅 ----
    "baggage": SubtypeRule("baggage", "行李托运", "other_travel", EVIDENCE_CONDITIONAL,
                           invoice_threshold=100, unit="元"),
    "visa": SubtypeRule("visa", "签证费", "other_travel", EVIDENCE_REQUIRED, unit="元"),
    "travel_insurance": SubtypeRule("travel_insurance", "差旅保险", "other_travel",
                                    EVIDENCE_CONDITIONAL, invoice_threshold=100, unit="元"),

    # ---- 招待 ----
    "banquet": SubtypeRule("banquet", "宴请", "entertainment", EVIDENCE_REQUIRED,
                           unit="元/次", note="需发票，注明招待对象与人数"),
    "gift": SubtypeRule("gift", "商务礼品", "entertainment", EVIDENCE_REQUIRED, unit="元"),

    # ---- 办公 ----
    "stationery": SubtypeRule("stationery", "办公用品", "office", EVIDENCE_CONDITIONAL,
                              invoice_threshold=100, unit="元"),
    "equipment": SubtypeRule("equipment", "办公设备", "office", EVIDENCE_REQUIRED, unit="元"),

    # ---- 通信 ----
    "phone_bill": SubtypeRule("phone_bill", "话费", "communication", EVIDENCE_SUBSIDY,
                              per_unit_limit=200, unit="元/月", note="岗位通信补贴，月度上限"),

    # ---- 培训 ----
    "training_fee": SubtypeRule("training_fee", "培训费", "training", EVIDENCE_REQUIRED, unit="元"),

    # ---- 其他 ----
    "misc": SubtypeRule("misc", "其他", "other", EVIDENCE_CONDITIONAL, invoice_threshold=100, unit="元"),
}


# 大额交易的统一发票门槛（补充规则）：任何单笔金额 ≥ 该值一律需要发票
GLOBAL_INVOICE_THRESHOLD = 500.0

# 整单总额超过该值 → 需上级/财务总监特殊审批
SPECIAL_APPROVAL_THRESHOLD = 50000.0


def get_subtype(code: str) -> SubtypeRule | None:
    return SUBTYPE_RULES.get(code)


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


def subtype_label(code: str) -> str:
    r = SUBTYPE_RULES.get(code)
    return r.label if r else code


def requires_invoice(subtype_code: str, amount: float, unit_price: float = 0.0) -> bool:
    """判断某笔费用是否必须提供发票。

    对多单位明细（如餐补 150/天×4天、住宿 500/晚×3晚），门槛判断针对【单价】
    而非累加总额，避免"多天补贴累加超门槛"被误判为需票。
    """
    rule = SUBTYPE_RULES.get(subtype_code)
    # 判据金额：有单价用单价，否则用总额
    basis = unit_price if unit_price and unit_price > 0 else amount
    if rule is None:
        return basis >= GLOBAL_INVOICE_THRESHOLD
    if rule.evidence == EVIDENCE_REQUIRED:
        return True
    if rule.evidence == EVIDENCE_SUBSIDY:
        # 补贴类：仅当单笔单价异常大时才要求发票（防滥用）
        return basis >= GLOBAL_INVOICE_THRESHOLD
    # conditional
    threshold = rule.invoice_threshold or GLOBAL_INVOICE_THRESHOLD
    return basis >= threshold


def is_subsidy(subtype_code: str, amount: float, unit_price: float = 0.0) -> bool:
    """该笔费用是否以补贴形式发放（无需发票）。"""
    rule = SUBTYPE_RULES.get(subtype_code)
    basis = unit_price if unit_price and unit_price > 0 else amount
    if rule is None:
        return basis < GLOBAL_INVOICE_THRESHOLD
    if rule.evidence == EVIDENCE_SUBSIDY:
        return basis < GLOBAL_INVOICE_THRESHOLD
    if rule.evidence == EVIDENCE_CONDITIONAL:
        threshold = rule.invoice_threshold or GLOBAL_INVOICE_THRESHOLD
        return basis < threshold
    return False


def normalize_subtype(text: str) -> str | None:
    """把自然语言/别名映射到标准子类代码。"""
    t = (text or "").strip().lower()
    if not t:
        return None
    if t in SUBTYPE_RULES:
        return t
    aliases = {
        "机票": "flight", "飞机": "flight", "航班": "flight",
        "火车": "train", "火车票": "train", "高铁": "train", "动车": "train",
        "大巴": "coach", "长途": "coach", "长途汽车": "coach", "客车": "coach",
        "打车": "taxi", "出租车": "taxi", "网约车": "taxi", "滴滴": "taxi", "taxi": "taxi",
        "地铁": "metro_bus", "公交": "metro_bus", "公交车": "metro_bus",
        "停车": "parking", "停车费": "parking",
        "油费": "fuel", "加油": "fuel",
        "住宿": "hotel", "酒店": "hotel", "宾馆": "hotel", "住宿费": "hotel",
        "餐补": "meal_allowance", "餐饮补贴": "meal_allowance", "吃饭": "meal_allowance",
        "餐饮": "meal_allowance", "伙食": "meal_allowance", "一日三餐": "meal_allowance",
        "商务宴请": "business_meal", "宴请客户": "business_meal", "请客": "business_meal",
        "行李": "baggage", "托运": "baggage",
        "签证": "visa",
        "保险": "travel_insurance", "差旅保险": "travel_insurance",
        "宴请": "banquet", "招待": "banquet",
        "礼品": "gift", "商务礼品": "gift",
        "办公用品": "stationery", "文具": "stationery",
        "设备": "equipment", "办公设备": "equipment",
        "话费": "phone_bill", "通信费": "phone_bill",
        "培训": "training_fee", "培训费": "training_fee",
    }
    for k, v in aliases.items():
        if k in t:
            return v
    return None


def all_subtypes_brief() -> str:
    """给 LLM 参考：按大类列出可用子类。"""
    from collections import defaultdict
    grouped: dict[str, list[str]] = defaultdict(list)
    for r in SUBTYPE_RULES.values():
        grouped[r.category].append(f"{r.code}({r.label})")
    lines = []
    for cat, items in grouped.items():
        lines.append(f"- {category_label(cat)}: {', '.join(items)}")
    return "\n".join(lines)
