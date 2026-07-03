"""
=============================================================================
app/agent/entities.py — 报销业务实体提取器
=============================================================================
从用户输入中提取报销领域的结构化实体。

区别于泛化 NER，本模块专门面向企业报销场景定义实体类型：

  核心实体:
    - department     : 部门名称
    - expense_type   : 费用类型 (travel/entertainment/office/other)
    - total_amount   : 报销金额（自动汇总多张发票）
    - expense_date   : 费用发生日期
    - description    : 费用说明

  差旅专属:
    - destination    : 目的地城市
    - travel_dates   : 出发-返回日期
    - transport_type : 交通方式 (flight/train/car)
    - hotel_days     : 住宿天数

  招待专属:
    - guest_count    : 招待人数
    - guest_company  : 对方公司名称
    - entertainment_purpose : 招待目的

  预支专属:
    - expected_date  : 预计使用日期
    - repayment_plan : 还款计划

  查询专属:
    - reimbursement_id : 报销单号（UUID 格式或短号）
    - date_range      : 查询日期范围 (start~end)

实体提取策略:
  1. 正则匹配：金额、日期、UUID 等结构化数据
  2. 词典匹配：部门名、费用类型、城市名
  3. LLM 提取：自然语言描述的复杂实体
=============================================================================
"""
import re
from dataclasses import dataclass, field
from typing import Optional


# =============================================================================
# 实体数据结构
# =============================================================================
@dataclass
class ReimbursementEntities:
    """报销业务实体集合"""
    # 基础实体
    department: str = ""
    expense_type: str = ""              # travel/entertainment/office/other
    total_amount: float = 0.0
    expense_date: str = ""              # YYYY-MM-DD
    description: str = ""

    # 差旅实体
    destination: str = ""               # 目的地城市
    travel_dates: str = ""              # "2026-06-15 ~ 2026-06-18"
    transport_type: str = ""            # flight/train/car
    hotel_days: int = 0

    # 招待实体
    guest_count: int = 0
    guest_company: str = ""
    entertainment_purpose: str = ""

    # 预支实体
    expected_date: str = ""
    repayment_plan: str = ""

    # 查询实体
    reimbursement_id: str = ""
    date_range: str = ""                # "2026-06-01~2026-06-30"

    # 元数据
    extraction_source: str = "rule"     # rule | llm | hybrid
    missing_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "department": self.department,
            "expense_type": self.expense_type,
            "total_amount": self.total_amount,
            "expense_date": self.expense_date,
            "description": self.description,
            "destination": self.destination,
            "travel_dates": self.travel_dates,
            "transport_type": self.transport_type,
            "hotel_days": self.hotel_days,
            "guest_count": self.guest_count,
            "guest_company": self.guest_company,
            "entertainment_purpose": self.entertainment_purpose,
            "expected_date": self.expected_date,
            "repayment_plan": self.repayment_plan,
            "reimbursement_id": self.reimbursement_id,
            "date_range": self.date_range,
            "extraction_source": self.extraction_source,
            "missing_fields": self.missing_fields,
        }

    def has_required(self, *fields: str) -> bool:
        """检查指定字段是否都已提取到"""
        return all(bool(getattr(self, f, None)) for f in fields)


# =============================================================================
# 词典定义
# =============================================================================
# 部门名词典（含常见缩写和别名）
DEPARTMENT_DICT = {
    "技术部", "研发部", "市场部", "销售部", "财务部",
    "人事部", "人力资源部", "行政部", "运营部", "运维部",
    "产品部", "设计部", "法务部", "公关部",
    "技术", "研发", "市场", "销售", "财务", "人事", "行政", "运营",
}

# 费用类型 → 标准化映射
EXPENSE_TYPE_MAP = {
    "差旅": "travel", "出差": "travel", "travel": "travel",
    "机票": "travel", "火车": "travel", "酒店": "travel", "住宿": "travel",
    "招待": "entertainment", "宴请": "entertainment", "请客": "entertainment",
    "entertainment": "entertainment",
    "办公": "office", "采购": "office", "文具": "office", "office": "office",
    "设备": "office", "耗材": "office",
    "other": "other", "其他": "other",
}

# 交通方式
TRANSPORT_DICT = {
    "飞机": "flight", "航班": "flight", "机票": "flight",
    "火车": "train", "高铁": "train", "动车": "train",
    "汽车": "car", "自驾": "car", "打车": "car", "出租车": "car",
}

# 中国主要城市（差旅目的地识别）
CITY_DICT = {
    "北京", "上海", "广州", "深圳", "杭州", "南京", "成都", "武汉",
    "西安", "重庆", "天津", "苏州", "长沙", "郑州", "青岛", "大连",
    "厦门", "福州", "合肥", "济南", "沈阳", "昆明", "贵阳", "南宁",
    "哈尔滨", "长春", "太原", "石家庄", "兰州", "乌鲁木齐", "海口", "三亚",
}


# =============================================================================
# 正则提取器
# =============================================================================
def _extract_amount(text: str) -> float:
    """
    从文本中提取金额。
    支持格式: "1500元" "¥1,500.00" "1,500" "1500"
    多金额时取第一个。
    """
    # 带货币符号的金额
    match = re.search(r"[¥￥]\s*([\d,]+(?:\.\d{1,2})?)", text)
    if match:
        return float(match.group(1).replace(",", ""))

    # 带"元"的金额
    match = re.search(r"(\d[\d,]*(?:\.\d{1,2})?)\s*(?:元|块|块钱)", text)
    if match:
        return float(match.group(1).replace(",", ""))

    # 纯数字（不太可靠，放最后）
    match = re.search(r"(\d{3,6}(?:\.\d{1,2})?)", text)
    if match:
        return float(match.group(1).replace(",", ""))

    return 0.0


def _extract_date(text: str) -> str:
    """提取日期，格式统一为 YYYY-MM-DD"""
    patterns = [
        r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2})[日号]?",   # 2026-06-15 / 2026年6月15日
        r"(\d{4}[-/]\d{1,2}[-/]\d{1,2})",               # 2026/06/15
    ]
    for pat in patterns:
        match = re.search(pat, text)
        if match:
            date_str = match.group(1)
            # 标准化为 YYYY-MM-DD
            date_str = date_str.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")
            return date_str
    return ""


def _extract_uuid(text: str) -> str:
    """提取 UUID 格式的报销单号"""
    match = re.search(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
        text,
    )
    return match.group(0) if match else ""


def _extract_guest_count(text: str) -> int:
    """提取人数"""
    match = re.search(r"(\d+)\s*(?:人|位|个)", text)
    return int(match.group(1)) if match else 0


def _extract_hotel_days(text: str) -> int:
    """提取住宿天数"""
    match = re.search(r"(\d+)\s*(?:天|晚|宿)", text)
    return int(match.group(1)) if match else 0


# =============================================================================
# 主提取函数
# =============================================================================
def extract_entities(text: str, llm_response: str = "") -> ReimbursementEntities:
    """
    从用户输入中提取所有报销相关实体。

    提取顺序：
      1. 正则提取结构化数据（金额、日期、UUID）
      2. 词典匹配（部门、费用类型、城市、交通方式）
      3. LLM 补充（自然语言中的隐含实体）

    Args:
        text         : 用户输入文本
        llm_response : LLM 返回的 JSON 实体（可选，用于补充规则提取不到的）

    Returns:
        ReimbursementEntities 对象
    """
    ent = ReimbursementEntities()

    # --- 步骤1：正则提取 ---
    ent.total_amount = _extract_amount(text)
    ent.expense_date = _extract_date(text)
    ent.reimbursement_id = _extract_uuid(text)
    ent.guest_count = _extract_guest_count(text)
    ent.hotel_days = _extract_hotel_days(text)

    # --- 步骤2：词典匹配 ---
    text_lower = text.lower()

    # 部门名匹配
    for dept in DEPARTMENT_DICT:
        if dept in text:
            ent.department = dept.rstrip("部") + "部" if not dept.endswith("部") else dept
            break

    # 费用类型匹配（最长的关键词优先，避免"差旅费"被"差旅"误匹配）
    sorted_types = sorted(EXPENSE_TYPE_MAP.items(), key=lambda x: -len(x[0]))
    for keyword, etype in sorted_types:
        if keyword in text_lower:
            ent.expense_type = etype
            break

    # 城市匹配
    for city in CITY_DICT:
        if city in text:
            ent.destination = city
            break

    # 交通方式匹配
    for keyword, ttype in TRANSPORT_DICT.items():
        if keyword in text:
            ent.transport_type = ttype
            break

    # --- 步骤3：LLM 补充（如果有）---
    if llm_response:
        try:
            import json
            llm_data = json.loads(llm_response)
            # 只在规则提取为空时才用 LLM 结果
            if not ent.department and llm_data.get("department"):
                ent.department = llm_data["department"]
            if not ent.expense_type and llm_data.get("expense_type"):
                ent.expense_type = llm_data["expense_type"]
            if ent.total_amount == 0 and llm_data.get("total_amount"):
                ent.total_amount = float(llm_data["total_amount"])
            if not ent.description and llm_data.get("description"):
                ent.description = llm_data["description"]
            if not ent.destination and llm_data.get("destination"):
                ent.destination = llm_data["destination"]
            if not ent.guest_count and llm_data.get("guest_count"):
                ent.guest_count = int(llm_data["guest_count"])
            ent.extraction_source = "hybrid"
        except (json.JSONDecodeError, ValueError, KeyError):
            pass

    if not ent.extraction_source:
        ent.extraction_source = "rule"

    # --- 步骤4：推断默认值 ---
    # 如果提取到了金额但没有费用类型，默认当作"其他"
    if ent.total_amount > 0 and not ent.expense_type:
        ent.expense_type = "other"

    # 如果提取到了机票/酒店但没有费用类型 → 差旅
    if ent.transport_type or ent.destination or ent.hotel_days > 0:
        if not ent.expense_type:
            ent.expense_type = "travel"

    return ent


def check_missing_slots(
    entities: ReimbursementEntities,
    required_slots: list[str],
) -> list[str]:
    """
    检查必需槽位是否都已填充。

    Args:
        entities       : 已提取的实体
        required_slots : 必需的字段名列表

    Returns:
        缺失的字段名列表（空列表 = 全部满足）
    """
    missing = []
    slot_checks = {
        "department": entities.department,
        "expense_type": entities.expense_type,
        "total_amount": entities.total_amount > 0,
        "reimbursement_id": entities.reimbursement_id,
        "action": True,  # action 在上下文中有默认值
        "file_path": True,  # 文件上传已单独处理
        "destination": entities.destination,
        "travel_dates": entities.travel_dates,
        "guest_count": entities.guest_count > 0,
        "guest_company": entities.guest_company,
        "expected_date": entities.expected_date,
        "repayment_plan": entities.repayment_plan,
        "date_range": entities.date_range,
    }

    for slot in required_slots:
        if not slot_checks.get(slot, False):
            missing.append(slot)

    return missing
