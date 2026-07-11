"""
=============================================================================
app/services/budget_admin_svc.py — 部门预算【人工管理】业务服务（阶段一）
=============================================================================
在既有「只读预算 + 报销状态机自动增减 used_amount」之上，新增企业运维所需的
【人工预算管理】能力，且不改动既有预算占用/释放模型：

  1. create_budget    — 新建部门预算
  2. adjust_annual    — 调整年度额度（增/减，或绝对改写）
  3. correct_used     — 人工冲正 used_amount（手工修账）
  4. transfer         — 部门间额度调拨（一增一减，同事务）
  5. list_adjustments — 查询某部门预算变更流水（审计）
  6. list_consumption — 查询占用某部门预算的报销单（消耗下钻）

一致性/并发：所有写操作在同一事务内 SELECT ... FOR UPDATE 锁定预算行后再改，
复用 reimbursement_svc.adjust_budget_used 的“原子自增 + 夹 0”，绝不新造第二套
预算增减逻辑。每次人工变更都落一条 budget_adjustment 审计记录。

校验逻辑全部下沉到 core/budget_admin_rules.py（纯函数，可单测）。
=============================================================================
"""
from __future__ import annotations

from decimal import Decimal
from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.reimbursement import DepartmentBudget, BudgetAdjustment, Reimbursement
from app.core.budget_rules import COMMITTED_STATUSES
from app.core import budget_admin_rules as rules
from app.core.exceptions import BudgetNotFoundError, BusinessException
from app.services.reimbursement_svc import adjust_budget_used


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


class BudgetAdminService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------ 内部工具
    async def _lock_budget(self, department: str) -> DepartmentBudget | None:
        """行锁读取部门预算（SELECT ... FOR UPDATE），不存在返回 None。"""
        return await self.db.scalar(
            select(DepartmentBudget)
            .where(DepartmentBudget.department == department)
            .with_for_update()
        )

    def _add_audit(self, *, department, fiscal_year, change_type,
                   delta_annual=0, delta_used=0, before_annual=None,
                   after_annual=None, operator, operator_role, reason) -> BudgetAdjustment:
        rec = BudgetAdjustment(
            department=department, fiscal_year=fiscal_year, change_type=change_type,
            delta_annual=_d(delta_annual), delta_used=_d(delta_used),
            before_annual=_d(before_annual) if before_annual is not None else None,
            after_annual=_d(after_annual) if after_annual is not None else None,
            operator=operator or "", operator_role=(operator_role or "").lower() or None,
            reason=reason or None,
        )
        self.db.add(rec)
        return rec

    # ------------------------------------------------------------ 1. 新建
    async def create_budget(
        self, department: str, annual_budget: float, fiscal_year: int,
        operator: str, operator_role: str, note: str | None = None,
    ) -> tuple[DepartmentBudget, BudgetAdjustment]:
        department = (department or "").strip()
        if not department:
            raise BusinessException("部门名称不能为空。", error_code="INVALID_DEPARTMENT")
        if annual_budget is None or float(annual_budget) <= 0:
            raise BusinessException("年度预算总额必须大于 0。", error_code="INVALID_BUDGET_AMOUNT")

        existing = await self.db.scalar(
            select(DepartmentBudget).where(DepartmentBudget.department == department)
        )
        if existing is not None:
            raise BusinessException(
                f"部门「{department}」的预算已存在，请使用调整接口修改额度。",
                error_code="BUDGET_ALREADY_EXISTS",
            )

        budget = DepartmentBudget(
            department=department, annual_budget=_d(annual_budget),
            used_amount=Decimal("0"), fiscal_year=int(fiscal_year),
            status="active", note=(note or None),
        )
        self.db.add(budget)
        await self.db.flush()
        audit = self._add_audit(
            department=department, fiscal_year=int(fiscal_year), change_type="create",
            delta_annual=annual_budget, before_annual=0, after_annual=annual_budget,
            operator=operator, operator_role=operator_role,
            reason=(note or "新建部门预算"),
        )
        await self.db.commit()
        await self.db.refresh(budget)
        await self.db.refresh(audit)
        logger.info(f"预算新建: {department} 年度=¥{float(annual_budget):,.2f} FY{fiscal_year} by {operator}({operator_role})")
        return budget, audit

    # ------------------------------------------------------------ 2. 调整额度
    async def adjust_annual(
        self, department: str, operator: str, operator_role: str, reason: str,
        delta: float | None = None, new_annual_budget: float | None = None,
        force: bool = False,
    ) -> tuple[DepartmentBudget, BudgetAdjustment]:
        budget = await self._lock_budget(department)
        if not budget:
            raise BudgetNotFoundError(department)

        current_annual = float(budget.annual_budget or 0)
        current_used = float(budget.used_amount or 0)
        try:
            target = rules.resolve_new_annual(current_annual, delta, new_annual_budget)
        except ValueError as e:
            raise BusinessException(str(e), error_code="INVALID_ADJUST_INPUT")

        ok, msg = rules.validate_annual_change(current_annual, current_used, target, force)
        if not ok:
            raise BusinessException(msg, error_code="INVALID_ANNUAL_CHANGE")

        delta_annual = target - current_annual
        if abs(delta_annual) < 1e-9:
            raise BusinessException("调整后额度与当前额度相同，无需变更。", error_code="NO_CHANGE")

        budget.annual_budget = _d(target)
        audit = self._add_audit(
            department=department, fiscal_year=budget.fiscal_year,
            change_type=rules.classify_annual_change(delta_annual),
            delta_annual=delta_annual, before_annual=current_annual, after_annual=target,
            operator=operator, operator_role=operator_role, reason=reason,
        )
        await self.db.commit()
        await self.db.refresh(budget)
        await self.db.refresh(audit)
        logger.info(
            f"预算调整: {department} 年度 ¥{current_annual:,.2f}→¥{target:,.2f} "
            f"(Δ{delta_annual:+,.2f}) by {operator}({operator_role}) 原因={reason}"
        )
        return budget, audit

    # ------------------------------------------------------------ 3. 人工冲正
    async def correct_used(
        self, department: str, delta_used: float, operator: str,
        operator_role: str, reason: str,
    ) -> tuple[DepartmentBudget, BudgetAdjustment]:
        budget = await self._lock_budget(department)
        if not budget:
            raise BudgetNotFoundError(department)

        current_used = float(budget.used_amount or 0)
        ok, msg, after_used = rules.validate_correction(current_used, delta_used)
        if not ok:
            raise BusinessException(msg, error_code="INVALID_CORRECTION")

        # 复用原子自增（负 delta 会释放；内部含夹 0），保持与报销侧同一套增减逻辑
        await adjust_budget_used(self.db, department, float(delta_used))
        # 记录“实际生效的冲正量”（考虑夹 0 后可能与传入不同）
        effective_delta = after_used - current_used
        audit = self._add_audit(
            department=department, fiscal_year=budget.fiscal_year, change_type="correction",
            delta_used=effective_delta, before_annual=float(budget.annual_budget or 0),
            after_annual=float(budget.annual_budget or 0),
            operator=operator, operator_role=operator_role, reason=reason,
        )
        await self.db.commit()
        fresh = await self.db.scalar(
            select(DepartmentBudget)
            .where(DepartmentBudget.department == department)
            .execution_options(populate_existing=True)
        )
        await self.db.refresh(audit)
        logger.info(
            f"预算冲正: {department} used ¥{current_used:,.2f}→¥{after_used:,.2f} "
            f"(Δ{effective_delta:+,.2f}) by {operator}({operator_role}) 原因={reason}"
        )
        return fresh, audit

    # ------------------------------------------------------------ 4. 部门调拨
    async def transfer(
        self, from_dept: str, to_dept: str, amount: float,
        operator: str, operator_role: str, reason: str, force: bool = False,
    ) -> tuple[DepartmentBudget, DepartmentBudget, list[BudgetAdjustment]]:
        from_dept = (from_dept or "").strip()
        to_dept = (to_dept or "").strip()
        # 先做无需 DB 的基础校验
        if amount is None or float(amount) <= 0:
            raise BusinessException("调拨金额必须大于 0。", error_code="INVALID_TRANSFER_AMOUNT")
        if from_dept == to_dept:
            raise BusinessException("转出部门与转入部门不能相同。", error_code="INVALID_TRANSFER_SAME_DEPT")

        # 按部门名排序加锁，避免两笔互向调拨并发时死锁
        first, second = sorted([from_dept, to_dept])
        b_first = await self._lock_budget(first)
        b_second = await self._lock_budget(second)
        budgets = {b.department: b for b in (b_first, b_second) if b is not None}
        if from_dept not in budgets:
            raise BudgetNotFoundError(from_dept)
        if to_dept not in budgets:
            raise BudgetNotFoundError(to_dept)

        b_from = budgets[from_dept]
        b_to = budgets[to_dept]
        ok, msg = rules.validate_transfer(
            from_dept, to_dept, float(amount),
            float(b_from.annual_budget or 0), float(b_from.used_amount or 0), force,
        )
        if not ok:
            raise BusinessException(msg, error_code="INVALID_TRANSFER")

        from_before = float(b_from.annual_budget or 0)
        to_before = float(b_to.annual_budget or 0)
        b_from.annual_budget = _d(from_before - float(amount))
        b_to.annual_budget = _d(to_before + float(amount))

        audit_out = self._add_audit(
            department=from_dept, fiscal_year=b_from.fiscal_year, change_type="transfer_out",
            delta_annual=-float(amount), before_annual=from_before,
            after_annual=from_before - float(amount),
            operator=operator, operator_role=operator_role,
            reason=f"调拨至「{to_dept}」：{reason}",
        )
        audit_in = self._add_audit(
            department=to_dept, fiscal_year=b_to.fiscal_year, change_type="transfer_in",
            delta_annual=float(amount), before_annual=to_before,
            after_annual=to_before + float(amount),
            operator=operator, operator_role=operator_role,
            reason=f"来自「{from_dept}」：{reason}",
        )
        await self.db.commit()
        await self.db.refresh(b_from)
        await self.db.refresh(b_to)
        await self.db.refresh(audit_out)
        await self.db.refresh(audit_in)
        logger.info(
            f"预算调拨: ¥{float(amount):,.2f} 「{from_dept}」→「{to_dept}」 "
            f"by {operator}({operator_role}) 原因={reason}"
        )
        return b_from, b_to, [audit_out, audit_in]

    # ------------------------------------------------------------ 5. 审计流水
    async def list_adjustments(self, department: str, limit: int = 50) -> list[BudgetAdjustment]:
        rows = (await self.db.execute(
            select(BudgetAdjustment)
            .where(BudgetAdjustment.department == department)
            .order_by(BudgetAdjustment.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )).scalars().all()
        return list(rows)

    # ------------------------------------------------------------ 6. 消耗下钻
    async def list_consumption(self, department: str, limit: int = 50) -> tuple[list[Reimbursement], float]:
        """列出占用该部门预算（pending/approved/paid）的报销单及其占用总额。"""
        conds = [
            Reimbursement.department == department,
            Reimbursement.status.in_(tuple(COMMITTED_STATUSES)),
        ]
        rows = (await self.db.execute(
            select(Reimbursement)
            .where(and_(*conds))
            .order_by(Reimbursement.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )).scalars().all()
        total = (await self.db.scalar(
            select(func.coalesce(func.sum(Reimbursement.total_amount), 0)).where(and_(*conds))
        )) or 0
        return list(rows), float(total)
