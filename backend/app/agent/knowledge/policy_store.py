"""
=============================================================================
app/agent/knowledge/policy_store.py — 策略数据层（替代硬编码规则）
=============================================================================
从知识库文档中动态解析费用标准，替代 policy.py 中的硬编码常量。

数据来源: data/knowledge/expense_policy.md
缓存机制: 首次加载后缓存，避免重复解析

设计目标:
  - 修改政策只需编辑 Markdown 文档，无需改代码
  - 支持结构化解析：费用类型 → 标准上限 → 附加规则
=============================================================================
"""
import re
from pathlib import Path
from loguru import logger

# =============================================================================
# 解析 expense_policy.md 中的结构化数据
# =============================================================================
_POLICY_CACHE: dict | None = None
_POLICY_FILE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "knowledge" / "expense_policy.md"


def _parse_policy_md() -> dict:
    """
    从 Markdown 文件中解析报销标准。

    解析逻辑:
      - ## 标题 → 费用类型名
      - **单次报销上限**: ¥10,000 → limit
      - **人均标准**: ¥200/人 → per_person
      - **住宿标准**: 关键词匹配
    """
    global _POLICY_CACHE
    if _POLICY_CACHE is not None:
        return _POLICY_CACHE

    policy = {
        "travel": {"name": "差旅费", "limit": 10000, "daily_limit": 500, "per_person": None, "rules": []},
        "entertainment": {"name": "招待费", "limit": 3000, "per_person": 200, "rules": []},
        "office": {"name": "办公费", "limit": 5000, "per_person": None, "rules": []},
        "other": {"name": "其他费用", "limit": 2000, "per_person": None, "rules": []},
        "hard_limit": 50000,
    }

    if not _POLICY_FILE.exists():
        logger.warning(f"Policy file not found: {_POLICY_FILE}, using defaults")
        _POLICY_CACHE = policy
        return policy

    content = _POLICY_FILE.read_text(encoding="utf-8")

    # 解析各费用类型
    sections = content.split("\n## ")
    current_type = ""
    for section in sections:
        section = section.strip()
        if not section:
            continue

        # 匹配费用类型标题
        type_match = re.match(r"([一二三四五六七八九十]+)、(.+?)\s*\((.+?)\)", section)
        if not type_match:
            type_match = re.match(r"(.+?)\s*\((.+?)\)", section)
        if type_match:
            current_type = type_match.group(2).strip() if type_match.lastindex >= 2 else ""

        # 映射中文名到英文 key
        type_key_map = {
            "差旅费": "travel", "招待费": "entertainment",
            "办公费": "office", "其他费用": "other",
        }
        if current_type in type_key_map:
            key = type_key_map[current_type]
            if key in policy:
                # 提取金额上限
                limit_match = re.search(r"不超过\s*[¥￥]\s*([\d,]+)", section)
                if limit_match:
                    policy[key]["limit"] = int(limit_match.group(1).replace(",", ""))

                # 人均标准
                per_match = re.search(r"人均.*?[¥￥]\s*([\d,]+)", section)
                if per_match:
                    policy[key]["per_person"] = int(per_match.group(1).replace(",", ""))

                # 日标准
                daily_match = re.search(r"[¥￥]\s*([\d,]+)\s*/天", section)
                if daily_match:
                    policy[key]["daily_limit"] = int(daily_match.group(1).replace(",", ""))

    # 解析硬限制
    hard_match = re.search(r"单次报销总金额不得超过\s*[¥￥]\s*([\d,]+)", content)
    if hard_match:
        policy["hard_limit"] = int(hard_match.group(1).replace(",", ""))

    _POLICY_CACHE = policy
    logger.info(f"Policy loaded from {_POLICY_FILE.name}: {len(policy)} types")
    return policy


def get_expense_limit(expense_type: str) -> float:
    """获取某费用类型的金额上限"""
    policy = _parse_policy_md()
    return policy.get(expense_type, {}).get("limit", 2000)


def get_per_person_limit(expense_type: str) -> float | None:
    """获取某费用类型的人均标准"""
    policy = _parse_policy_md()
    return policy.get(expense_type, {}).get("per_person")


def get_daily_limit(expense_type: str) -> float | None:
    """获取某费用类型的日标准"""
    policy = _parse_policy_md()
    return policy.get(expense_type, {}).get("daily_limit")


def get_all_policies() -> dict:
    """获取全部政策数据"""
    return _parse_policy_md()


def reload_policies():
    """强制重新加载政策（用于热更新）"""
    global _POLICY_CACHE
    _POLICY_CACHE = None
    return _parse_policy_md()
