"""
=============================================================================
app/services/expense_sheet_svc.py — 报销单（费用明细）业务服务
=============================================================================
企业级分步报销：
  1. 创建报销单草稿（draft）
  2. 逐条添加费用明细行（交通/住宿/餐饮/…），自动判断是否需发票/补贴
  3. 为明细行关联发票
  4. 提交前严格校验（大额必须有发票、补贴规则、金额一致性）
  5. 提交 → 合规 + 预算检查 + 状态置为 pending 进入审批

所有金额用 Decimal 精确计算，汇总自动重算，权限由调用方（工具/API）保证。
=============================================================================
"""
from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from loguru import logger

from app.models.reimbursement import (
    Reimbursement, ExpenseItem, Invoice, DepartmentBudget, ApprovalRecord,
)
from app.agent import expense_rules as rules
from app.core.exceptions import ReimbursementNotFoundError, BusinessException


def _d(v) -> Decimal:
    return Decimal(str(v or 0))


class ExpenseSheetService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------ 读取
    async def get(self, reimb_id: str) -> Reimbursement:
        # populate_existing 强制用最新数据刷新身份映射里的实例及其集合关系，
        # 避免读到 add/remove 之前缓存的旧 items/invoices（且不会像 expire_all 那样
        # 误伤同请求内其它已加载对象，触发异步惰性加载 MissingGreenlet）。
        stmt = (
            select(Reimbursement)
            .options(
                selectinload(Reimbursement.items).selectinload(ExpenseItem.invoices),
                selectinload(Reimbursement.approvals),
            )
            .where(Reimbursement.id == reimb_id)
            .execution_options(populate_existing=True)
        )
        reimb = (await self.db.execute(stmt)).scalar_one_or_none()
        if not reimb:
            raise ReimbursementNotFoundError(reimb_id)
        return reimb

    async def find_active_draft(self, user_id: str) -> Reimbursement | None:
        """查用户最近一个 draft 报销单（用于"继续上一张"场景）。"""
        stmt = (
            select(Reimbursement)
            .where(Reimbursement.user_id == user_id, Reimbursement.status == "draft")
            .order_by(Reimbursement.updated_at.desc())
            .limit(1)
        )
        reimb = (await self.db.execute(stmt)).scalar_one_or_none()
        if reimb:
            return await self.get(reimb.id)
        return None

    # ------------------------------------------------------------------ 建单
    async def create_draft(
        self, user_id: str, user_name: str, department: str,
        expense_type: str = "travel", title: str = "",
        trip_destination: str = "", trip_start_date: str = "",
        trip_end_date: str = "", description: str = "",
    ) -> Reimbursement:
        d_start = _parse_date(trip_start_date)
        d_end = _parse_date(trip_end_date)
        trip_days = None
        if d_start and d_end and d_end >= d_start:
            trip_days = (d_end - d_start).days + 1
        reimb = Reimbursement(
            user_id=user_id, user_name=user_name, department=department,
            expense_type=expense_type or "travel",
            title=title or (f"{trip_destination}出差报销" if trip_destination else "报销单"),
            total_amount=0, invoice_amount=0, subsidy_amount=0,
            trip_destination=trip_destination or None,
            trip_start_date=d_start, trip_end_date=d_end, trip_days=trip_days,
            description=description or None,
            status="draft",
        )
        self.db.add(reimb)
        await self.db.commit()
        await self.db.refresh(reimb)
        logger.info(f"报销草稿已创建: {reimb.id} user={user_name} type={expense_type}")
        return await self.get(reimb.id)

    # ------------------------------------------------------------------ 加明细
    async def add_item(
        self, reimb_id: str, subtype: str, amount: float = 0,
        unit_price: float = 0, quantity: float = 0,
        description: str = "", occur_date: str = "",
        from_location: str = "", to_location: str = "",
    ) -> tuple[Reimbursement, ExpenseItem]:
        """
        添加一条费用明细。金额规则：
          - 若给了 unit_price + quantity → amount = unit_price × quantity
          - 否则用传入 amount
        自动判定 needs_invoice / is_subsidy（依据 expense_rules）。
        """
        reimb = await self.get(reimb_id)
        if reimb.status != "draft":
            raise BusinessException(f"报销单当前状态为 {reimb.status}，只有草稿可以继续添加明细。",
                                    error_code="NOT_DRAFT")

        code = rules.normalize_subtype(subtype) or subtype
        rule = rules.get_subtype(code)
        if rule is None:
            raise BusinessException(
                f"无法识别的费用子类：{subtype}。可用子类见费用分类表。",
                error_code="UNKNOWN_SUBTYPE",
            )

        up = _d(unit_price)
        qty = _d(quantity)
        if up > 0 and qty > 0:
            amt = up * qty
        else:
            amt = _d(amount)
            if qty <= 0:
                qty = Decimal("1")
        if amt <= 0:
            raise BusinessException("费用金额必须大于 0。", error_code="INVALID_AMOUNT")

        amt_f = float(amt)
        up_f = float(up) if up > 0 else 0.0
        needs_invoice = rules.requires_invoice(code, amt_f, up_f)
        is_subsidy = rules.is_subsidy(code, amt_f, up_f)

        # 下一个 seq
        max_seq = (await self.db.execute(
            select(func.coalesce(func.max(ExpenseItem.seq), 0))
            .where(ExpenseItem.reimbursement_id == reimb_id)
        )).scalar() or 0

        item = ExpenseItem(
            reimbursement_id=reimb_id, seq=max_seq + 1,
            category=rule.category, subtype=code,
            description=description or rule.label,
            unit_price=up if up > 0 else None,
            quantity=qty, unit=rule.unit or None,
            amount=amt,
            evidence_type=rule.evidence,
            is_subsidy=is_subsidy, needs_invoice=needs_invoice, has_invoice=False,
            occur_date=_parse_date(occur_date),
            from_location=from_location or None, to_location=to_location or None,
        )
        self.db.add(item)
        await self.db.flush()
        await self._recalc(reimb)
        await self.db.commit()
        logger.info(f"明细已添加: reimb={reimb_id} {code} ¥{amt_f} needs_invoice={needs_invoice} subsidy={is_subsidy}")
        fresh = await self.get(reimb_id)
        # 返回重载后的同一条明细（其 invoices 已 eager-load，避免惰性加载）
        fresh_item = next((it for it in fresh.items if it.seq == item.seq), item)
        return fresh, fresh_item

    # -------------------------------------------------------------- 删除明细
    async def remove_item(self, reimb_id: str, item_seq: int) -> Reimbursement:
        reimb = await self.get(reimb_id)
        if reimb.status != "draft":
            raise BusinessException(f"报销单状态为 {reimb.status}，不可修改明细。", error_code="NOT_DRAFT")
        target = next((it for it in reimb.items if it.seq == item_seq), None)
        if not target:
            raise BusinessException(f"未找到序号为 {item_seq} 的明细。", error_code="ITEM_NOT_FOUND")
        await self.db.delete(target)
        await self.db.flush()
        await self._recalc(reimb)
        await self.db.commit()
        return await self.get(reimb_id)

    # ------------------------------------------------------ 为明细关联发票
    async def attach_invoice_to_item(
        self, reimb_id: str, item_seq: int, invoice: dict,
    ) -> Reimbursement:
        reimb = await self.get(reimb_id)
        if reimb.status != "draft":
            raise BusinessException(f"报销单状态为 {reimb.status}，不可修改。", error_code="NOT_DRAFT")
        target = next((it for it in reimb.items if it.seq == item_seq), None)
        if not target:
            raise BusinessException(f"未找到序号为 {item_seq} 的明细。", error_code="ITEM_NOT_FOUND")
        inv = Invoice(
            reimbursement_id=reimb_id, expense_item_id=target.id,
            invoice_code=invoice.get("invoice_code") or "",
            invoice_number=invoice.get("invoice_number") or "",
            invoice_date=_parse_date(invoice.get("invoice_date")),
            invoice_type=invoice.get("invoice_type") or "",
            seller_name=invoice.get("seller_name") or "",
            buyer_name=invoice.get("buyer_name") or "",
            amount=_d(invoice.get("amount") or target.amount),
            tax_amount=_d(invoice.get("tax_amount")),
            total_with_tax=_d(invoice.get("total_with_tax") or invoice.get("amount") or target.amount),
            file_path=invoice.get("file_path") or "",
        )
        self.db.add(inv)
        target.has_invoice = True
        await self.db.flush()
        await self._recalc(reimb)
        await self.db.commit()
        return await self.get(reimb_id)

    # ------------------------------------------------------------------ 校验
    def validate(self, reimb: Reimbursement) -> dict:
        """
        提交前严格校验，返回 {ok, errors, warnings, missing_invoices}。
        """
        errors: list[str] = []
        warnings: list[str] = []
        missing_invoices: list[dict] = []

        if not reimb.items:
            errors.append("报销单没有任何费用明细，请先添加。")

        for it in reimb.items:
            label = rules.subtype_label(it.subtype)
            # 大额/必须发票项：检查是否已关联发票
            if it.needs_invoice and not (it.invoices and len(it.invoices) > 0):
                missing_invoices.append({
                    "seq": it.seq, "subtype": it.subtype, "label": label,
                    "amount": float(it.amount),
                })
                errors.append(f"明细#{it.seq}「{label} ¥{float(it.amount):,.2f}」为大额/必须凭票项，缺少发票。")
            # 单价/日限校验（软性 → warning）
            rule = rules.get_subtype(it.subtype)
            if rule and rule.per_unit_limit and it.unit_price and float(it.unit_price) > rule.per_unit_limit:
                warnings.append(
                    f"明细#{it.seq}「{label}」单价 ¥{float(it.unit_price):,.2f} 超过标准 "
                    f"¥{rule.per_unit_limit:,.2f}{('/' + rule.unit) if rule.unit else ''}，超出部分可能需说明。"
                )
            # 发票金额与明细金额一致性（软性）
            if it.invoices:
                inv_sum = sum(float(v.amount or 0) for v in it.invoices)
                if abs(inv_sum - float(it.amount)) > 0.01:
                    warnings.append(
                        f"明细#{it.seq}「{label}」发票合计 ¥{inv_sum:,.2f} 与明细金额 "
                        f"¥{float(it.amount):,.2f} 不一致，请核对。"
                    )

        return {
            "ok": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "missing_invoices": missing_invoices,
        }

    # ------------------------------------------------------------------ 提交
    async def submit(self, reimb_id: str) -> dict:
        """
        提交报销单：校验 → 预算检查 → 状态置 pending + 初始审批记录。
        返回 {success, reimb_id, need_special_approval, validation, message}。
        """
        reimb = await self.get(reimb_id)
        if reimb.status != "draft":
            return {"success": False, "message": f"报销单已是「{reimb.status}」状态，无需重复提交。"}

        await self._recalc(reimb)
        v = self.validate(reimb)
        if not v["ok"]:
            return {"success": False, "validation": v,
                    "message": "报销单未通过校验，请先补齐必要发票/信息。"}

        # 预算检查
        budget = await self.db.scalar(
            select(DepartmentBudget).where(DepartmentBudget.department == reimb.department)
        )
        if not budget:
            return {"success": False, "message": f"未找到部门「{reimb.department}」的预算配置，请联系财务部。"}

        total = _d(reimb.total_amount)
        remaining = budget.annual_budget - budget.used_amount
        remaining_after = remaining - total
        need_special = (remaining_after < 0) or (float(total) >= rules.SPECIAL_APPROVAL_THRESHOLD)

        budget.used_amount = budget.used_amount + total
        reimb.budget_remaining_after = remaining_after
        reimb.need_special_approval = need_special
        reimb.status = "pending"

        # 初始审批记录
        self.db.add(ApprovalRecord(
            reimbursement_id=reimb.id, approver="部门经理", step=1,
            action="pending", comment="报销单已提交，等待审批",
        ))
        if need_special:
            self.db.add(ApprovalRecord(
                reimbursement_id=reimb.id, approver="财务总监", step=2,
                action="pending", comment="金额较大/预算超标，需特殊审批",
            ))
        await self.db.commit()
        logger.info(f"报销单已提交: {reimb.id} total={float(total)} special={need_special}")
        return {
            "success": True, "reimb_id": reimb.id,
            "total_amount": float(total),
            "invoice_amount": float(reimb.invoice_amount or 0),
            "subsidy_amount": float(reimb.subsidy_amount or 0),
            "need_special_approval": need_special,
            "validation": v,
            "message": "报销单已提交，进入审批流程。" + ("（金额较大/预算超标，需特殊审批）" if need_special else ""),
        }

    # ------------------------------------------------------------ 汇总重算
    async def _recalc(self, reimb: Reimbursement) -> None:
        """重算报销单总额 / 发票额 / 补贴额 / 发票张数。"""
        # 重新载入 items（确保最新）
        items = (await self.db.execute(
            select(ExpenseItem).where(ExpenseItem.reimbursement_id == reimb.id)
        )).scalars().all()
        total = Decimal("0")
        inv_amt = Decimal("0")
        sub_amt = Decimal("0")
        for it in items:
            total += _d(it.amount)
            if it.is_subsidy:
                sub_amt += _d(it.amount)
            else:
                inv_amt += _d(it.amount)
        inv_count = (await self.db.execute(
            select(func.count()).select_from(Invoice).where(Invoice.reimbursement_id == reimb.id)
        )).scalar() or 0
        reimb.total_amount = total
        reimb.invoice_amount = inv_amt
        reimb.subsidy_amount = sub_amt
        reimb.invoice_count = inv_count


def _parse_date(v) -> date | None:
    if not v:
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None
