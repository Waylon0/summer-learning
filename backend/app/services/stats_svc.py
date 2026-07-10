"""
=============================================================================
app/services/stats_svc.py — 统计与发票台账业务逻辑层
=============================================================================
对应 docs/BACKEND-API-NEEDS.md 的接口需求，提供两个服务类：

  1. StatsService          — 费用趋势 / 个人统计 / 部门排行 / 汇总卡片
  2. InvoiceLedgerService  — 发票台账列表（多维度筛选 + 分页）

设计说明：
  - 日期比较沿用项目既有约定（与 ReimbursementService.search 一致）：
    直接用 ISO 日期字符串与 created_at 比较，兼容 PostgreSQL / SQLite。
  - 月份分桶在 Python 中完成，避免 to_char / strftime 的方言差异。
=============================================================================
"""
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger


def _to_dt(d: date) -> datetime:
    """把 date 转成带时区的 datetime（当天 00:00 UTC）。

    PostgreSQL 的 created_at 是 TIMESTAMPTZ，直接与字符串比较会报
    'operator does not exist: timestamp with time zone >= character varying'，
    因此所有区间比较统一使用 timezone-aware datetime。
    """
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

from app.models.reimbursement import Reimbursement, Invoice, DepartmentBudget, ExpenseItem
from app.models.user import User
from app.agent import expense_rules as _erules
from app.schemas.stats import (
    TrendSeries, TrendResponse,
    MonthStat, StatusBreakdown, PersonalStatsResponse,
    DepartmentRankingItem, DepartmentRankingResponse,
    InvoiceLedgerItem, InvoiceListResponse,
    SummaryResponse,
)

# 折线图固定的 4 个费用类型分桶（其余类型归入 other）
STANDARD_TREND_TYPES: list[tuple[str, str]] = [
    ("travel", "差旅费"),
    ("entertainment", "招待费"),
    ("office", "办公用品"),
    ("other", "其他"),
]
_TREND_KNOWN = {"travel", "entertainment", "office"}

# 参与统计的有效状态（排除 rejected / cancelled / returned）
_ACTIVE_STATUS = ["approved", "pending", "paid"]


def _trend_bucket(expense_type: str) -> str:
    """把顶层费用类型归到折线图的 4 个分桶之一。"""
    return expense_type if expense_type in _TREND_KNOWN else "other"


# =============================================================================
# 日期工具函数
# =============================================================================
def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """在 (year, month) 基础上偏移 delta 个月，返回新的 (year, month)"""
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _last_n_months(n: int, ref: date | None = None) -> list[str]:
    """返回最近 n 个月（含当前月）的 'YYYY-MM' 列表，从旧到新排序"""
    ref = ref or date.today()
    months = []
    for i in range(n - 1, -1, -1):
        y, m = _add_months(ref.year, ref.month, -i)
        months.append(f"{y:04d}-{m:02d}")
    return months


def _month_bounds(ref: date) -> tuple[date, date]:
    """返回 ref 所在月的 [起始日, 次月起始日)"""
    start = date(ref.year, ref.month, 1)
    ny, nm = _add_months(ref.year, ref.month, 1)
    return start, date(ny, nm, 1)


def _parse_month(month: str | None) -> date | None:
    """把 'YYYY-MM' 解析为该月 1 号的 date，非法则返回 None"""
    if not month:
        return None
    try:
        y, m = month.split("-")
        return date(int(y), int(m), 1)
    except (ValueError, AttributeError):
        return None


def _period_start(period: str) -> date:
    """根据 period（month/quarter/year）返回统计起始日期"""
    today = date.today()
    if period == "month":
        return date(today.year, today.month, 1)
    if period == "quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        return date(today.year, q_start_month, 1)
    return date(today.year, 1, 1)  # year（默认）


# =============================================================================
# 统计服务
# =============================================================================
class StatsService:
    """费用统计业务逻辑"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ 趋势
    async def trend(self, months: int = 6, department: str | None = None) -> TrendResponse:
        """近 N 个月费用趋势，按【费用明细的类别】分色。

        真实报销单常跨多类费用（差旅单里也可能含办公明细），因此按明细类别
        （经 expense_rules 映射到顶层类型）分桶，比只看报销单主类型更准确。
        无明细的历史/兼容报销单，则回退按其报销单主类型计入。
        """
        from collections import defaultdict
        months = max(1, min(months, 24))
        month_list = _last_n_months(months)
        first_y, first_m = int(month_list[0][:4]), int(month_list[0][5:7])
        start_dt = _to_dt(date(first_y, first_m, 1))

        conditions = [
            Reimbursement.status.in_(_ACTIVE_STATUS),
            Reimbursement.created_at >= start_dt,
        ]
        if department:
            conditions.append(Reimbursement.department == department)

        # 左连接明细：有明细的按明细类别，无明细的回退按报销单主类型
        rows = (
            await self.db.execute(
                select(
                    Reimbursement.id,
                    Reimbursement.created_at,
                    Reimbursement.expense_type,
                    Reimbursement.total_amount,
                    ExpenseItem.subtype,
                    ExpenseItem.amount,
                )
                .outerjoin(ExpenseItem, ExpenseItem.reimbursement_id == Reimbursement.id)
                .where(and_(*conditions))
            )
        ).all()

        buckets = {t: {m: 0.0 for m in month_list} for t, _ in STANDARD_TREND_TYPES}
        valid_months = set(month_list)

        grouped: dict = defaultdict(list)
        for rid, created_at, etype, total, subtype, amount in rows:
            grouped[rid].append((created_at, etype, total, subtype, amount))

        for rid, rrows in grouped.items():
            created_at, etype, total = rrows[0][0], rrows[0][1], rrows[0][2]
            if not created_at:
                continue
            m = created_at.strftime("%Y-%m")
            if m not in valid_months:
                continue
            has_items = any(r[3] is not None for r in rrows)
            if has_items:
                for _, _, _, subtype, amount in rrows:
                    if subtype is None:
                        continue
                    bucket = _trend_bucket(_erules.expense_type_for_subtype(subtype))
                    buckets[bucket][m] += float(amount or 0)
            else:
                buckets[_trend_bucket(etype or "other")][m] += float(total or 0)

        series = [
            TrendSeries(
                expense_type=t,
                label=label,
                data=[round(buckets[t][m], 2) for m in month_list],
            )
            for t, label in STANDARD_TREND_TYPES
        ]
        logger.info(f"费用趋势查询(按明细类别): months={months} dept={department} reimb数={len(grouped)}")
        return TrendResponse(months=month_list, series=series)

    # -------------------------------------------------------------- 个人统计
    async def personal(self, user_id: str, month: str | None = None) -> PersonalStatsResponse:
        """当前用户报销统计（本月 / 上月 / 状态分布）"""
        ref = _parse_month(month) or date.today()
        cur_start, cur_end = _month_bounds(ref)
        py, pm = _add_months(ref.year, ref.month, -1)
        prev_start, _ = _month_bounds(date(py, pm, 1))

        # 用户姓名：优先取用户表，回退到报销单
        user = await self.db.get(User, user_id)
        user_name = user.name if user else ""
        if not user_name:
            user_name = await self.db.scalar(
                select(Reimbursement.user_name)
                .where(Reimbursement.user_id == user_id)
                .limit(1)
            ) or ""

        current = await self._month_stat(user_id, cur_start, cur_end)
        last = await self._month_stat(user_id, prev_start, cur_start)
        breakdown = await self._status_breakdown(user_id, cur_start, cur_end)

        logger.info(f"个人统计查询: user_id={user_id} month={ref:%Y-%m}")
        return PersonalStatsResponse(
            user_name=user_name,
            current_month=current,
            last_month=last,
            status_breakdown=breakdown,
        )

    async def _month_stat(self, user_id: str, start: date, end: date) -> MonthStat:
        """某用户在 [start, end) 区间内的报销单数量与总额"""
        row = (
            await self.db.execute(
                select(
                    func.count(Reimbursement.id),
                    func.coalesce(func.sum(Reimbursement.total_amount), 0),
                ).where(
                    Reimbursement.user_id == user_id,
                    Reimbursement.created_at >= _to_dt(start),
                    Reimbursement.created_at < _to_dt(end),
                )
            )
        ).one()
        return MonthStat(count=row[0] or 0, total=float(row[1] or 0))

    async def _status_breakdown(self, user_id: str, start: date, end: date) -> StatusBreakdown:
        """某用户在 [start, end) 区间内按状态分组的数量"""
        rows = (
            await self.db.execute(
                select(Reimbursement.status, func.count(Reimbursement.id))
                .where(
                    Reimbursement.user_id == user_id,
                    Reimbursement.created_at >= _to_dt(start),
                    Reimbursement.created_at < _to_dt(end),
                )
                .group_by(Reimbursement.status)
            )
        ).all()
        counts = {status: count for status, count in rows}
        return StatusBreakdown(
            pending=counts.get("pending", 0),
            approved=counts.get("approved", 0) + counts.get("paid", 0),
            rejected=counts.get("rejected", 0),
        )

    # -------------------------------------------------------------- 部门排行
    async def department_ranking(self, period: str = "year") -> DepartmentRankingResponse:
        """部门费用排行"""
        if period not in ("month", "quarter", "year"):
            period = "year"
        start = _period_start(period)

        budgets = {
            b.department: b
            for b in (await self.db.execute(select(DepartmentBudget))).scalars().all()
        }

        rows = (
            await self.db.execute(
                select(
                    Reimbursement.department,
                    func.coalesce(func.sum(Reimbursement.total_amount), 0),
                )
                .where(
                    Reimbursement.status.in_(_ACTIVE_STATUS),
                    Reimbursement.created_at >= _to_dt(start),
                )
                .group_by(Reimbursement.department)
            )
        ).all()
        spend = {dept: float(total or 0) for dept, total in rows}

        items = []
        for dept in set(budgets) | set(spend):
            total = spend.get(dept, 0.0)
            budget = float(budgets[dept].annual_budget) if dept in budgets else 0.0
            usage_rate = round(total / budget * 100, 2) if budget > 0 else 0.0
            items.append(
                DepartmentRankingItem(
                    department=dept, total=round(total, 2),
                    budget=budget, usage_rate=usage_rate,
                )
            )
        items.sort(key=lambda x: x.total, reverse=True)
        logger.info(f"部门排行查询: period={period} 部门数={len(items)}")
        return DepartmentRankingResponse(rankings=items)

    # ------------------------------------------------------------------ 汇总
    async def summary(self) -> SummaryResponse:
        """Dashboard 顶部汇总卡片"""
        budget_row = (
            await self.db.execute(
                select(
                    func.coalesce(func.sum(DepartmentBudget.annual_budget), 0),
                    func.coalesce(func.sum(DepartmentBudget.used_amount), 0),
                )
            )
        ).one()
        annual_total = float(budget_row[0] or 0)
        used_total = float(budget_row[1] or 0)

        pending_row = (
            await self.db.execute(
                select(
                    func.count(Reimbursement.id),
                    func.coalesce(func.sum(Reimbursement.total_amount), 0),
                ).where(Reimbursement.status == "pending")
            )
        ).one()

        today = date.today()
        cur_start, cur_end = _month_bounds(today)
        py, pm = _add_months(today.year, today.month, -1)
        prev_start, _ = _month_bounds(date(py, pm, 1))

        this_month_total = await self._sum_in_period(cur_start, cur_end)
        last_month_total = await self._sum_in_period(prev_start, cur_start)

        logger.info("汇总卡片查询")
        return SummaryResponse(
            annual_budget_total=round(annual_total, 2),
            used_total=round(used_total, 2),
            remaining_total=round(annual_total - used_total, 2),
            pending_count=pending_row[0] or 0,
            pending_amount=float(pending_row[1] or 0),
            this_month_total=round(this_month_total, 2),
            last_month_total=round(last_month_total, 2),
        )

    async def _sum_in_period(self, start: date, end: date) -> float:
        """[start, end) 区间内有效状态报销单的总额"""
        total = await self.db.scalar(
            select(func.coalesce(func.sum(Reimbursement.total_amount), 0)).where(
                Reimbursement.status.in_(_ACTIVE_STATUS),
                Reimbursement.created_at >= _to_dt(start),
                Reimbursement.created_at < _to_dt(end),
            )
        )
        return float(total or 0)


# =============================================================================
# 发票台账服务
# =============================================================================
class InvoiceLedgerService:
    """发票台账查询业务逻辑"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_invoices(
        self,
        page: int = 1,
        page_size: int = 20,
        date_from: str | None = None,
        date_to: str | None = None,
        amount_min: float | None = None,
        amount_max: float | None = None,
        expense_type: str | None = None,
        seller_name: str | None = None,
        keyword: str | None = None,
        user: User | None = None,
    ) -> InvoiceListResponse:
        """多维度筛选 + 分页查询发票台账（含权限隔离）"""
        page = max(1, page)
        page_size = max(1, min(page_size, 200))

        conditions = []
        # 权限隔离：员工仅本人、经理仅本部门，管理员/财务全部
        if user is not None:
            if user.role == "employee":
                conditions.append(Reimbursement.user_id == user.id)
            elif user.role == "manager":
                conditions.append(Reimbursement.department == user.department)
        d_from = self._parse_date(date_from)
        d_to = self._parse_date(date_to)
        if d_from:
            conditions.append(Invoice.invoice_date >= d_from)
        if d_to:
            conditions.append(Invoice.invoice_date <= d_to)
        if amount_min is not None:
            conditions.append(Invoice.amount >= Decimal(str(amount_min)))
        if amount_max is not None:
            conditions.append(Invoice.amount <= Decimal(str(amount_max)))
        if expense_type:
            conditions.append(Reimbursement.expense_type == expense_type)
        if seller_name:
            conditions.append(Invoice.seller_name.ilike(f"%{seller_name}%"))
        if keyword:
            conditions.append(
                or_(
                    Invoice.invoice_code.ilike(f"%{keyword}%"),
                    Invoice.invoice_number.ilike(f"%{keyword}%"),
                )
            )
        where_clause = and_(*conditions) if conditions else True

        join_from = select(Invoice, Reimbursement.expense_type).join(
            Reimbursement, Invoice.reimbursement_id == Reimbursement.id
        )

        count_stmt = (
            select(func.count())
            .select_from(Invoice)
            .join(Reimbursement, Invoice.reimbursement_id == Reimbursement.id)
            .where(where_clause)
        )
        total = (await self.db.execute(count_stmt)).scalar() or 0

        offset = (page - 1) * page_size
        stmt = (
            join_from.where(where_clause)
            .order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        rows = (await self.db.execute(stmt)).all()

        items = [
            InvoiceLedgerItem(
                id=inv.id,
                invoice_code=inv.invoice_code or "",
                invoice_number=inv.invoice_number or "",
                amount=float(inv.amount or 0),
                invoice_date=inv.invoice_date.isoformat() if inv.invoice_date else None,
                seller_name=inv.seller_name or "",
                buyer_name=inv.buyer_name or "",
                expense_type=etype or "",
                reimbursement_id=inv.reimbursement_id,
                file_path=inv.file_path or "",
            )
            for inv, etype in rows
        ]
        logger.info(f"发票台账查询: {len(items)}/{total} 条 page={page}")
        return InvoiceListResponse(total=total, items=items)

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        """把 'YYYY-MM-DD' 解析为 date，非法则返回 None"""
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
