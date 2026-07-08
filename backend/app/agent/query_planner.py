"""
=============================================================================
app/agent/query_planner.py — 报销单动态查询规划器（安全版）
=============================================================================
目标：
  让 Agent 灵活理解用户自然语言查询意图（可任意组合筛选条件），
  同时严格保证安全与权限，不允许任何自由 SQL。

安全设计（核心）：
  1. LLM 只负责把自然语言 → 结构化「查询计划」(QueryPlan JSON)，
     绝不生成 SQL 文本。
  2. 查询计划中的字段名、操作符、排序键全部走白名单校验，
     非法值直接丢弃。
  3. 真正的 SQL 由 SQLAlchemy ORM 以「参数化」方式构建，
     天然免疫 SQL 注入；且只可能是 SELECT。
  4. 权限过滤在代码层「强制注入」，与 LLM 输出无关：
       - employee : 只能查本人 (user_id == 自己)
       - manager  : 只能查本部门 (department == 自己部门)
       - admin/finance : 可查全部
     用户在自然语言里要求越权（如员工查别人）时，
     权限过滤仍然生效，越权条件被忽略或收窄。
=============================================================================
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

from loguru import logger
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.reimbursement import Reimbursement


# =============================================================================
# 白名单常量
# =============================================================================
# 状态：中文/英文 → 标准值
STATUS_ALIASES: dict[str, str] = {
    "待审批": "pending", "待审": "pending", "审批中": "pending", "pending": "pending",
    "已通过": "approved", "通过": "approved", "批准": "approved", "同意": "approved", "approved": "approved",
    "已驳回": "rejected", "驳回": "rejected", "拒绝": "rejected", "被拒": "rejected", "rejected": "rejected",
    "已退回": "returned", "退回": "returned", "打回": "returned", "returned": "returned",
    "已付款": "paid", "已付": "paid", "付款": "paid", "已报销": "paid", "paid": "paid",
    "已撤销": "cancelled", "撤销": "cancelled", "取消": "cancelled", "cancelled": "cancelled",
}
VALID_STATUSES = {"pending", "approved", "rejected", "returned", "paid", "cancelled"}

# 费用类型合法值（与 validators.KNOWN_EXPENSE_TYPES 对齐的常用子集）
VALID_EXPENSE_TYPES = {
    "travel", "entertainment", "office", "communication", "transport",
    "meeting", "training", "other", "rd_materials", "rd_equipment",
    "tech_acquisition", "software_license", "advertisement", "exhibition",
    "client_maintenance", "audit", "recruitment", "renovation", "cloud_service",
}

# 排序字段白名单（防注入 + 防越权列）
SORT_COLUMNS = {
    "created_at": Reimbursement.created_at,
    "total_amount": Reimbursement.total_amount,
    "department": Reimbursement.department,
    "status": Reimbursement.status,
    "expense_type": Reimbursement.expense_type,
}

STATUS_LABELS = {
    "pending": "待审批", "approved": "已通过", "rejected": "已驳回",
    "returned": "已退回", "paid": "已付款", "cancelled": "已撤销",
}
TYPE_LABELS = {
    "travel": "差旅费", "entertainment": "招待费", "office": "办公用品",
    "communication": "通信费", "transport": "市内交通费", "meeting": "会议费",
    "training": "培训费", "other": "其他费用", "rd_materials": "研发材料费",
    "rd_equipment": "研发设备费", "tech_acquisition": "技术引进费",
    "software_license": "软件许可费", "advertisement": "广告推广费",
    "exhibition": "展会费", "client_maintenance": "客户维护费",
    "audit": "审计服务费", "recruitment": "招聘费", "renovation": "装修费",
    "cloud_service": "云服务费",
}

MAX_LIMIT = 100


# =============================================================================
# 查询计划数据结构
# =============================================================================
@dataclass
class QueryPlan:
    """结构化查询计划 —— 全部字段都是安全白名单值。"""
    status: Optional[str] = None                 # 单状态
    statuses: list[str] = field(default_factory=list)  # 多状态（如"已通过或已付款"）
    department: Optional[str] = None
    expense_type: Optional[str] = None
    user_name: Optional[str] = None              # 按申请人姓名（模糊）
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    amount_exact: Optional[float] = None
    date_from: Optional[str] = None              # YYYY-MM-DD
    date_to: Optional[str] = None
    keyword: Optional[str] = None                # 描述模糊搜索
    sort_by: str = "created_at"
    sort_dir: str = "desc"
    limit: int = 30

    def to_summary(self) -> str:
        """人类可读的筛选条件摘要（用于回复展示）。"""
        parts = []
        if self.statuses:
            parts.append("状态∈[" + "/".join(STATUS_LABELS.get(s, s) for s in self.statuses) + "]")
        elif self.status:
            parts.append("状态=" + STATUS_LABELS.get(self.status, self.status))
        if self.department:
            parts.append("部门=" + self.department)
        if self.expense_type:
            parts.append("类型=" + TYPE_LABELS.get(self.expense_type, self.expense_type))
        if self.user_name:
            parts.append("申请人~" + self.user_name)
        if self.amount_exact is not None:
            parts.append(f"金额=¥{self.amount_exact:,.2f}")
        else:
            if self.amount_min is not None:
                parts.append(f"金额≥¥{self.amount_min:,.2f}")
            if self.amount_max is not None:
                parts.append(f"金额≤¥{self.amount_max:,.2f}")
        if self.date_from:
            parts.append(f"起={self.date_from}")
        if self.date_to:
            parts.append(f"止={self.date_to}")
        if self.keyword:
            parts.append(f"关键词~{self.keyword}")
        return ", ".join(parts) if parts else "无（全部）"


# =============================================================================
# 安全清洗：把任意 dict → 合法 QueryPlan
# =============================================================================
def _coerce_amount(val) -> Optional[float]:
    try:
        f = float(val)
        return f if f >= 0 else None
    except (TypeError, ValueError):
        return None


def _coerce_date(val) -> Optional[str]:
    """接受 YYYY-MM-DD / YYYY-MM，返回规范化 YYYY-MM-DD，非法返回 None。"""
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", val)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return None
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", val)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"{y:04d}-{mo:02d}-01"
    return None


def sanitize_plan(raw: dict) -> QueryPlan:
    """把（可能来自 LLM 的）原始 dict 清洗成安全的 QueryPlan。非法字段一律丢弃。"""
    plan = QueryPlan()
    if not isinstance(raw, dict):
        return plan

    # --- 状态（单个 + 多个）---
    def _norm_status(s):
        if not isinstance(s, str):
            return None
        s = s.strip()
        if s in VALID_STATUSES:
            return s
        return STATUS_ALIASES.get(s)

    raw_statuses = raw.get("statuses")
    if isinstance(raw_statuses, list):
        seen = []
        for s in raw_statuses:
            ns = _norm_status(s)
            if ns and ns not in seen:
                seen.append(ns)
        plan.statuses = seen
    single = _norm_status(raw.get("status"))
    if single and not plan.statuses:
        plan.status = single

    # --- 部门（原样保留字符串，参数化查询，无注入风险）---
    dept = raw.get("department")
    if isinstance(dept, str) and dept.strip():
        plan.department = dept.strip()[:64]

    # --- 费用类型（白名单）---
    etype = raw.get("expense_type")
    if isinstance(etype, str) and etype.strip() in VALID_EXPENSE_TYPES:
        plan.expense_type = etype.strip()

    # --- 申请人姓名（模糊）---
    uname = raw.get("user_name")
    if isinstance(uname, str) and uname.strip():
        plan.user_name = uname.strip()[:64]

    # --- 金额 ---
    plan.amount_exact = _coerce_amount(raw.get("amount_exact"))
    if plan.amount_exact is None:
        plan.amount_min = _coerce_amount(raw.get("amount_min"))
        plan.amount_max = _coerce_amount(raw.get("amount_max"))
        # min>max 时交换，避免空结果
        if (plan.amount_min is not None and plan.amount_max is not None
                and plan.amount_min > plan.amount_max):
            plan.amount_min, plan.amount_max = plan.amount_max, plan.amount_min

    # --- 日期 ---
    plan.date_from = _coerce_date(raw.get("date_from"))
    plan.date_to = _coerce_date(raw.get("date_to"))

    # --- 关键词 ---
    kw = raw.get("keyword")
    if isinstance(kw, str) and kw.strip():
        plan.keyword = kw.strip()[:64]

    # --- 排序（白名单）---
    sb = raw.get("sort_by")
    if isinstance(sb, str) and sb in SORT_COLUMNS:
        plan.sort_by = sb
    sd = raw.get("sort_dir")
    if isinstance(sd, str) and sd.lower() in ("asc", "desc"):
        plan.sort_dir = sd.lower()

    # --- 分页上限 ---
    try:
        lim = int(raw.get("limit", 30))
        plan.limit = max(1, min(lim, MAX_LIMIT))
    except (TypeError, ValueError):
        plan.limit = 30

    return plan


# =============================================================================
# 规则兜底提取（LLM 不可用时）
# =============================================================================
def rule_extract_plan(text: str) -> dict:
    """基于规则从自然语言抽取查询计划（LLM 兜底）。返回原始 dict，交给 sanitize_plan。"""
    raw: dict = {}
    t = text.strip()

    # 状态（支持多状态："已通过或已驳回"）
    found_status = []
    for kw, val in STATUS_ALIASES.items():
        if kw in t and val not in found_status:
            # 避免 "通过" 命中 "未通过" 之类，简单包含即可满足绝大多数场景
            found_status.append(val)
    if len(found_status) > 1:
        raw["statuses"] = found_status
    elif len(found_status) == 1:
        raw["status"] = found_status[0]

    # 部门
    from app.agent.entities import DEPARTMENT_DICT
    for dept in sorted(DEPARTMENT_DICT, key=len, reverse=True):
        if dept in t:
            raw["department"] = dept.rstrip("部") + "部" if not dept.endswith("部") else dept
            break

    # 费用类型
    from app.agent.entities import EXPENSE_TYPE_MAP
    for kw, etype in sorted(EXPENSE_TYPE_MAP.items(), key=lambda x: -len(x[0])):
        if kw in t.lower():
            raw["expense_type"] = etype
            break

    # 金额范围
    m = re.search(r"(?:大于|超过|高于|多于|>=|>|不低于|至少)\s*[¥￥]?\s*(\d[\d,]*(?:\.\d+)?)", t)
    if m:
        raw["amount_min"] = float(m.group(1).replace(",", ""))
    m = re.search(r"(?:小于|低于|少于|不超过|不高于|<=|<|至多|最多)\s*[¥￥]?\s*(\d[\d,]*(?:\.\d+)?)", t)
    if m:
        raw["amount_max"] = float(m.group(1).replace(",", ""))
    # 区间 "1000到5000" / "1000-5000元" / "1000~5000"
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(?:到|至|~|-|—)\s*(\d[\d,]*(?:\.\d+)?)\s*元?", t)
    if m and "amount_min" not in raw and "amount_max" not in raw:
        raw["amount_min"] = float(m.group(1).replace(",", ""))
        raw["amount_max"] = float(m.group(2).replace(",", ""))

    # 日期范围
    from app.agent.entities import _extract_date
    m = re.search(r"(.+?)\s*(?:到|至|~|-|—)\s*(.+)", t)
    # 交给 _extract_date 逐段尝试（简单处理）
    d = _extract_date(t)
    if d:
        # 若文本含"之后/以来/起" → date_from；含"之前/以前/截止" → date_to
        if any(k in t for k in ["之后", "以来", "起", "开始"]):
            raw["date_from"] = d
        elif any(k in t for k in ["之前", "以前", "截止", "前"]):
            raw["date_to"] = d

    return raw


# =============================================================================
# LLM 查询计划提取
# =============================================================================
async def extract_plan_with_llm(text: str, llm_caller) -> Optional[dict]:
    """
    调用 LLM 抽取查询计划。

    Args:
        text       : 用户自然语言
        llm_caller : async 函数 (messages)->str，复用 graph._try_llm_async

    Returns:
        原始 dict（未清洗），失败返回 None
    """
    from langchain_core.messages import HumanMessage
    from app.agent.prompts import QUERY_PLANNER_PROMPT

    resp = await llm_caller([
        HumanMessage(content=f"{QUERY_PLANNER_PROMPT}\n\n用户查询: {text}\n\nJSON:")
    ])
    if not resp:
        return None
    content = resp.strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        data = json.loads(content)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


# =============================================================================
# 权限作用域 —— 强制注入，与 LLM 输出无关
# =============================================================================
def apply_permission_scope(
    plan: QueryPlan,
    user_id: str,
    user_role: str,
    user_department: str,
) -> tuple[list, Optional[str]]:
    """
    根据当前用户角色，生成「强制」权限过滤条件。

    返回:
      (额外的 SQLAlchemy 条件列表, 越权提示 or None)

    规则:
      - employee : 强制 user_id == 自己。忽略 plan.user_name（不能查别人）。
      - manager  : 强制 department == 自己部门。忽略 plan.department 的跨部门值。
      - admin/finance : 无限制。
      - 未登录/未知角色 : 最严格，视为无权限，返回一个永假条件。
    """
    conditions = []
    notice = None
    role = (user_role or "").lower()

    if role in ("admin", "finance"):
        # 全局权限，不加限制
        return conditions, notice

    if role == "manager":
        if not user_department:
            conditions.append(Reimbursement.id == "__no_permission__")
            return conditions, "无法确定您的部门，暂无法查询。"
        # 强制限定本部门；若用户请求了别的部门 → 忽略并提示
        if plan.department and plan.department != user_department:
            notice = f"您是「{user_department}」经理，只能查看本部门数据，已忽略对「{plan.department}」的查询。"
        plan.department = user_department  # 覆盖，防越权
        conditions.append(Reimbursement.department == user_department)
        return conditions, notice

    if role == "employee":
        if not user_id:
            conditions.append(Reimbursement.id == "__no_permission__")
            return conditions, "无法确定您的身份，暂无法查询。"
        # 强制只看自己；忽略按他人姓名/部门的查询
        if plan.user_name:
            notice = "您只能查询本人的报销单，已忽略对其他申请人的查询。"
        plan.user_name = None
        plan.department = None
        conditions.append(Reimbursement.user_id == user_id)
        return conditions, notice

    # 未登录 / 未知角色：拒绝
    conditions.append(Reimbursement.id == "__no_permission__")
    return conditions, "您尚未登录，无法查询报销单。"


# =============================================================================
# 安全执行器 —— 用 ORM 参数化构建 SELECT
# =============================================================================
async def execute_plan(
    db: AsyncSession,
    plan: QueryPlan,
    user_id: str,
    user_role: str,
    user_department: str,
) -> tuple[list[dict], int, Optional[str]]:
    """
    根据查询计划执行安全查询。

    所有条件均通过 SQLAlchemy 表达式构建（参数化），
    只产生 SELECT，且强制叠加权限过滤。

    Returns:
      (结果列表, 命中总数, 越权/权限提示)
    """
    conditions = []

    # --- 1) 业务筛选条件（来自已清洗的 plan）---
    if plan.statuses:
        conditions.append(Reimbursement.status.in_(plan.statuses))
    elif plan.status:
        conditions.append(Reimbursement.status == plan.status)
    if plan.expense_type:
        conditions.append(Reimbursement.expense_type == plan.expense_type)
    if plan.keyword:
        conditions.append(Reimbursement.description.ilike(f"%{plan.keyword}%"))
    if plan.amount_exact is not None:
        conditions.append(Reimbursement.total_amount == Decimal(str(plan.amount_exact)))
    else:
        if plan.amount_min is not None:
            conditions.append(Reimbursement.total_amount >= Decimal(str(plan.amount_min)))
        if plan.amount_max is not None:
            conditions.append(Reimbursement.total_amount <= Decimal(str(plan.amount_max)))
    if plan.date_from:
        conditions.append(Reimbursement.created_at >= plan.date_from)
    if plan.date_to:
        # date_to 视为当天结束：<= date_to 23:59:59
        conditions.append(Reimbursement.created_at <= f"{plan.date_to} 23:59:59")

    # --- 2) 权限作用域（强制，可能会修改 plan.department/user_name）---
    perm_conditions, notice = apply_permission_scope(plan, user_id, user_role, user_department)

    # 权限收窄后再叠加 plan 里的部门/姓名（employee 已被清空；manager 已被强制本部门）
    if plan.department:
        conditions.append(Reimbursement.department == plan.department)
    if plan.user_name:
        conditions.append(Reimbursement.user_name.ilike(f"%{plan.user_name}%"))

    conditions.extend(perm_conditions)
    where_clause = and_(*conditions) if conditions else True

    # --- 3) 排序（白名单列）---
    sort_col = SORT_COLUMNS.get(plan.sort_by, Reimbursement.created_at)
    order_clause = sort_col.asc() if plan.sort_dir == "asc" else sort_col.desc()

    # --- 4) 计数 + 取数（参数化，纯 SELECT）---
    total = (await db.execute(
        select(func.count()).select_from(Reimbursement).where(where_clause)
    )).scalar() or 0

    stmt = (
        select(Reimbursement)
        .options(selectinload(Reimbursement.approvals))
        .where(where_clause)
        .order_by(order_clause)
        .limit(plan.limit)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    results = [
        {
            "reimb_id": r.id,
            "user_name": r.user_name,
            "department": r.department,
            "expense_type": r.expense_type,
            "total_amount": float(r.total_amount),
            "status": r.status,
            "description": r.description or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "need_special_approval": r.need_special_approval,
        }
        for r in rows
    ]

    logger.info(
        f"[QueryPlanner] role={user_role} filters=({plan.to_summary()}) "
        f"→ {len(results)}/{total} 条"
        + (f" | notice={notice}" if notice else "")
    )
    return results, total, notice
