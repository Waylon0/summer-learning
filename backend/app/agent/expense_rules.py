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

# 整单总额超过该值 → 标记需特殊审批（提示财务在阶段二审慎复核，不增加审批层级）
SPECIAL_APPROVAL_THRESHOLD = 50000.0


def get_subtype(code: str) -> SubtypeRule | None:
    return SUBTYPE_RULES.get(code)


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category, category)


# =============================================================================
# 细粒度分类 → 顶层费用类型 的映射
# -----------------------------------------------------------------------------
# 顶层类型（travel/entertainment/office/communication/training/other）用于统计口径、
# 报销单主类型、费用标准（expense_policy）对齐。一张报销单的 expense_type 由其明细
# 自动推导（占比最大的类型），避免"差旅单里混入办公明细却仍标 travel"污染报表。
# =============================================================================
CATEGORY_TO_EXPENSE_TYPE = {
    "transport_intercity": "travel",
    "transport_local": "travel",
    "accommodation": "travel",
    "meal": "travel",
    "other_travel": "travel",
    "entertainment": "entertainment",
    "office": "office",
    "communication": "communication",
    "training": "training",
    "other": "other",
}

# 子类级别覆盖（商务宴请虽属"餐饮"大类，但按招待费口径归类）
_SUBTYPE_TYPE_OVERRIDE = {
    "business_meal": "entertainment",
}


def expense_type_for_subtype(subtype_code: str) -> str:
    """把费用子类映射到顶层费用类型。"""
    if subtype_code in _SUBTYPE_TYPE_OVERRIDE:
        return _SUBTYPE_TYPE_OVERRIDE[subtype_code]
    r = SUBTYPE_RULES.get(subtype_code)
    if r:
        return CATEGORY_TO_EXPENSE_TYPE.get(r.category, "other")
    return "other"


def derive_expense_type(items, default: str = "travel") -> str:
    """依据明细（金额占比最大的顶层类型）推导报销单主费用类型。

    items: 可迭代的 (subtype_code, amount) 二元组。无明细时返回 default。
    """
    from collections import defaultdict
    agg: dict[str, float] = defaultdict(float)
    for subtype_code, amount in items:
        agg[expense_type_for_subtype(subtype_code)] += float(amount or 0)
    if not agg:
        return default
    return max(agg.items(), key=lambda kv: (kv[1], kv[0]))[0]


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


# 按"出差天数"约束数量的子类（餐补按天、住宿按晚）
_TRIP_BOUND_UNITS = {"meal_allowance": "天", "hotel": "晚"}

# 招待类"人均"上限（元/人），与知识库招待费标准一致
_PER_PERSON_LIMIT = {"banquet": 200.0, "business_meal": 200.0}
# 需要登记"招待对象/人数"的子类
ENTERTAIN_SUBTYPES = frozenset({"banquet", "business_meal"})


def per_person_limit(subtype_code: str) -> float:
    """招待类人均上限（0 表示该子类无人均限制）。"""
    return float(_PER_PERSON_LIMIT.get(subtype_code, 0.0))


def exceeds_per_person_limit(subtype_code: str, amount, attendee_count) -> tuple[bool, float, float]:
    """判断招待类明细是否超过人均标准。返回 (是否超标, 人均, 上限)。

    未提供人数或该子类无人均限制时不判定超标。
    """
    limit = per_person_limit(subtype_code)
    try:
        n = int(attendee_count or 0)
    except (TypeError, ValueError):
        n = 0
    if limit <= 0 or n <= 0:
        return (False, 0.0, limit)
    per = float(amount or 0) / n
    return (per > limit + 1e-6, per, limit)


def invoice_date_status(invoice_date, ref_date, max_age_days: int = 90) -> str:
    """发票开票日期相对报销/参考日的状态：ok / future（晚于参考日）/ stale（超期）。

    invoice_date、ref_date 为 datetime.date；任一缺失时返回 ok（不判定）。
    """
    if not invoice_date or not ref_date:
        return "ok"
    if invoice_date > ref_date:
        return "future"
    if (ref_date - invoice_date).days > max_age_days:
        return "stale"
    return "ok"


def quantity_vs_trip_days(subtype_code: str, quantity, trip_days) -> tuple[bool, str]:
    """判断按天/按晚计的明细数量是否超过出差天数。

    返回 (是否超出, 单位)。仅对餐补(天)/住宿(晚)生效；trip_days 未知则不判定。
    """
    unit = _TRIP_BOUND_UNITS.get(subtype_code, "")
    if not unit or not trip_days or not quantity:
        return (False, unit)
    return (float(quantity) > float(trip_days) + 1e-6, unit)


def per_unit_limit(subtype_code: str) -> float:
    """返回子类的单价/单日/单位上限（0 表示不限）。"""
    r = SUBTYPE_RULES.get(subtype_code)
    return float(r.per_unit_limit) if r else 0.0


def effective_unit_price(unit_price, amount, quantity) -> float:
    """推算一条明细的"有效单价"，用于与单位上限比较。

    - 已显式录入单价 → 直接用单价（如 住宿 500/晚、餐补 150/天）。
    - 未录入单价但数量>1 → 用 金额/数量 反推单价。
    - 否则视为单笔金额即单价。
    """
    up = float(unit_price or 0)
    if up > 0:
        return up
    q = float(quantity or 0)
    amt = float(amount or 0)
    if q > 1:
        return amt / q
    return amt


def exceeds_unit_limit(subtype_code: str, unit_price=0, amount=0, quantity=0) -> tuple[bool, float, float]:
    """判断某明细是否超过单位上限。

    返回 (是否超标, 有效单价, 上限)。上限为 0（不限）时永不超标。
    """
    limit = per_unit_limit(subtype_code)
    if limit <= 0:
        return False, effective_unit_price(unit_price, amount, quantity), 0.0
    eup = effective_unit_price(unit_price, amount, quantity)
    return (eup > limit + 1e-6), eup, limit


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
