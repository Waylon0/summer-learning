"""
=============================================================================
app/schemas/stats.py — 统计与发票台账的响应模型（Pydantic Schemas）
=============================================================================
对应 docs/BACKEND-API-NEEDS.md 中前端需要的接口：
  1. TrendResponse            — GET /stats/trend         费用趋势折线图
  2. PersonalStatsResponse    — GET /stats/personal      个人报销统计
  3. DepartmentRankingResponse— GET /stats/department-ranking 部门费用排行
  4. InvoiceListResponse      — GET /invoices            发票台账列表
  5. SummaryResponse          — GET /stats/summary       Dashboard 汇总卡片
=============================================================================
"""
from pydantic import BaseModel, Field


# =============================================================================
# 1. 费用趋势
# =============================================================================
class TrendSeries(BaseModel):
    """折线图中的一条曲线（对应一种费用类型）"""
    expense_type: str                       # 费用类型英文标识
    label: str                              # 费用类型中文名
    data: list[float]                       # 每个月的金额（与 months 一一对应）


class TrendResponse(BaseModel):
    """近 N 个月费用趋势"""
    months: list[str]                       # 月份列表，如 ["2026-02", ...]
    series: list[TrendSeries]               # 按费用类型分色的数据系列


# =============================================================================
# 2. 个人报销统计
# =============================================================================
class MonthStat(BaseModel):
    """某个月的报销统计"""
    count: int                              # 报销单数量
    total: float                            # 报销总额


class StatusBreakdown(BaseModel):
    """按状态拆分的数量"""
    pending: int = 0
    approved: int = 0
    rejected: int = 0


class PersonalStatsResponse(BaseModel):
    """当前用户报销统计"""
    user_name: str
    current_month: MonthStat
    last_month: MonthStat
    status_breakdown: StatusBreakdown


# =============================================================================
# 3. 部门费用排行
# =============================================================================
class DepartmentRankingItem(BaseModel):
    """单个部门的费用排行项"""
    department: str
    total: float                            # 期间内费用合计
    budget: float                           # 年度预算
    usage_rate: float                       # 使用率（百分比）


class DepartmentRankingResponse(BaseModel):
    """部门费用排行榜"""
    rankings: list[DepartmentRankingItem]


# =============================================================================
# 4. 发票台账
# =============================================================================
class InvoiceLedgerItem(BaseModel):
    """发票台账中的一条发票"""
    id: str
    invoice_code: str
    invoice_number: str
    amount: float
    invoice_date: str | None = None
    seller_name: str
    buyer_name: str
    expense_type: str                       # 来自关联报销单
    reimbursement_id: str
    file_path: str


class InvoiceListResponse(BaseModel):
    """发票台账分页结果"""
    total: int
    items: list[InvoiceLedgerItem]


# =============================================================================
# 5. Dashboard 汇总卡片
# =============================================================================
class SummaryResponse(BaseModel):
    """首页 / Dashboard 顶部汇总卡片"""
    annual_budget_total: float              # 年度预算总额
    used_total: float                       # 已使用总额
    remaining_total: float                  # 剩余总额
    pending_count: int                      # 待审批数量
    pending_amount: float                   # 待审批金额
    this_month_total: float                 # 本月报销总额
    last_month_total: float                 # 上月报销总额
