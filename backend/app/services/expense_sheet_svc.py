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

from decimal import Decimal, ROUND_HALF_UP
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


_CENT = Decimal("0.01")


def _q(v: Decimal) -> Decimal:
    """按分（2 位小数）四舍五入量化金额，明确进位规则。"""
    return _d(v).quantize(_CENT, rounding=ROUND_HALF_UP)


def _compute_item_financials(code, rule, amount, unit_price, quantity, currency, exchange_rate):
    """由输入金额字段计算一条明细的最终财务字段（含外币折算与单据判定）。

    返回 dict(amt, up, qty, cur, rate, original_amount, needs_invoice, is_subsidy)，
    金额均为人民币本位币。供 add_item / update_item 复用，保证口径一致。
    """
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

    cur = (currency or "CNY").strip().upper() or "CNY"
    rate = _d(exchange_rate)
    original_amount = None
    if cur != "CNY":
        if rate <= 0:
            raise BusinessException(
                "外币报销请提供汇率(exchange_rate，1 外币=? 人民币)。",
                error_code="EXCHANGE_RATE_REQUIRED",
            )
        original_amount = _q(amt)
        amt = amt * rate
        if up > 0:
            up = _q(up * rate)

    amt = _q(amt)
    up = _q(up) if up > 0 else up
    amt_f = float(amt)
    up_f = float(up) if up > 0 else 0.0
    return {
        "amt": amt, "up": up, "qty": qty, "cur": cur, "rate": rate,
        "original_amount": original_amount,
        "needs_invoice": rules.requires_invoice(code, amt_f, up_f),
        "is_subsidy": rules.is_subsidy(code, amt_f, up_f),
    }


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

    # -------------------------------------------------------------- 可编辑性
    def _assert_editable(self, reimb: Reimbursement) -> None:
        """确保报销单处于可编辑状态。

        - draft：可编辑。
        - returned（被退回修改）：自动"重新打开"为 draft 后可编辑，
          从而让退回流程真正闭环（可改明细/补票并重新提交）。
        - 其他状态（pending/approved/rejected/paid/cancelled）：拒绝修改。
        """
        if reimb.status == "draft":
            return
        if reimb.status == "returned":
            reimb.status = "draft"
            logger.info(f"报销单 {reimb.id} 由 returned 重新打开为 draft（退回后再编辑）")
            return
        raise BusinessException(
            f"报销单当前状态为 {reimb.status}，不可修改明细。", error_code="NOT_DRAFT"
        )

    async def reopen(self, reimb_id: str) -> Reimbursement:
        """把被退回（returned）的报销单重新打开为草稿，便于修改后重新提交。"""
        reimb = await self.get(reimb_id)
        if reimb.status == "draft":
            return reimb
        if reimb.status != "returned":
            raise BusinessException(
                f"报销单当前状态为 {reimb.status}，仅「已退回」的报销单可重新打开。",
                error_code="NOT_RETURNED",
            )
        reimb.status = "draft"
        await self.db.commit()
        logger.info(f"报销单已重新打开: {reimb_id}")
        return await self.get(reimb_id)

    async def cleanup_stale_drafts(self, days: int = 30) -> int:
        """清理长期未更新（默认 30 天）且【无任何明细】的空草稿，返回清理条数。

        仅删除空草稿，避免误删用户正在填写的内容；有明细的旧草稿保留。
        """
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(days=max(1, days))
        rows = (await self.db.execute(
            select(Reimbursement)
            .options(selectinload(Reimbursement.items))
            .where(Reimbursement.status == "draft", Reimbursement.updated_at < cutoff)
        )).scalars().all()
        removed = 0
        for reimb in rows:
            if not reimb.items:
                await self.db.delete(reimb)
                removed += 1
        if removed:
            await self.db.commit()
        logger.info(f"清理过期空草稿: {removed} 条（阈值 {days} 天）")
        return removed

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
        from_location: str = "", to_location: str = "", remark: str = "",
        attendee_count: int = 0, guest_info: str = "",
        currency: str = "CNY", exchange_rate: float = 0,
    ) -> tuple[Reimbursement, ExpenseItem]:
        """
        添加一条费用明细。金额规则：
          - 若给了 unit_price + quantity → amount = unit_price × quantity
          - 否则用传入 amount
          - 外币（currency != CNY）需提供 exchange_rate（1 外币=?人民币），
            系统按 CNY 本位币折算后再参与限额/预算/汇总（amount 恒为 CNY）。
        自动判定 needs_invoice / is_subsidy（依据 expense_rules，基于折算后 CNY 金额）。
        """
        reimb = await self.get(reimb_id)
        self._assert_editable(reimb)

        code = rules.normalize_subtype(subtype) or subtype
        rule = rules.get_subtype(code)
        if rule is None:
            raise BusinessException(
                f"无法识别的费用子类：{subtype}。可用子类见费用分类表。",
                error_code="UNKNOWN_SUBTYPE",
            )

        fin = _compute_item_financials(code, rule, amount, unit_price, quantity, currency, exchange_rate)

        # 下一个 seq
        max_seq = (await self.db.execute(
            select(func.coalesce(func.max(ExpenseItem.seq), 0))
            .where(ExpenseItem.reimbursement_id == reimb_id)
        )).scalar() or 0

        item = ExpenseItem(
            reimbursement_id=reimb_id, seq=max_seq + 1,
            category=rule.category, subtype=code,
            description=description or rule.label,
            unit_price=fin["up"] if fin["up"] > 0 else None,
            quantity=fin["qty"], unit=rule.unit or None,
            amount=fin["amt"],
            currency=fin["cur"],
            exchange_rate=fin["rate"] if fin["cur"] != "CNY" else None,
            original_amount=fin["original_amount"],
            evidence_type=rule.evidence,
            is_subsidy=fin["is_subsidy"], needs_invoice=fin["needs_invoice"], has_invoice=False,
            occur_date=_parse_date(occur_date),
            from_location=from_location or None, to_location=to_location or None,
            remark=remark or None,
            attendee_count=int(attendee_count) if attendee_count else None,
            guest_info=guest_info or None,
        )
        self.db.add(item)
        await self.db.flush()
        await self._recalc(reimb)
        await self.db.commit()
        logger.info(f"明细已添加: reimb={reimb_id} {code} ¥{float(fin['amt'])}({fin['cur']}) needs_invoice={fin['needs_invoice']} subsidy={fin['is_subsidy']}")
        fresh = await self.get(reimb_id)
        # 返回重载后的同一条明细（其 invoices 已 eager-load，避免惰性加载）
        fresh_item = next((it for it in fresh.items if it.seq == item.seq), item)
        return fresh, fresh_item

    # -------------------------------------------------------------- 修改明细
    async def update_item(
        self, reimb_id: str, item_seq: int, subtype: str = "",
        amount: float = 0, unit_price: float = 0, quantity: float = 0,
        description: str = None, occur_date: str = "",
        from_location: str = None, to_location: str = None, remark: str = None,
        attendee_count: int = None, guest_info: str = None,
        currency: str = "", exchange_rate: float = 0,
    ) -> tuple[Reimbursement, ExpenseItem]:
        """修改一条已存在的费用明细（保留其已关联发票，避免删了重建丢发票）。

        - 传了金额字段（amount 或 unit_price+quantity）则重算金额与单据判定；
          未传则沿用原金额，仅按（可能变更的）子类重算是否需票/补贴。
        - description/remark/地点/招待要素等：传了才更新（None 表示不改）。
        """
        reimb = await self.get(reimb_id)
        self._assert_editable(reimb)
        target = next((it for it in reimb.items if it.seq == item_seq), None)
        if not target:
            raise BusinessException(f"未找到序号为 {item_seq} 的明细。", error_code="ITEM_NOT_FOUND")

        code = (rules.normalize_subtype(subtype) or subtype) if subtype else target.subtype
        rule = rules.get_subtype(code)
        if rule is None:
            raise BusinessException(
                f"无法识别的费用子类：{subtype}。", error_code="UNKNOWN_SUBTYPE",
            )

        money_provided = (amount and amount > 0) or (unit_price > 0 and quantity > 0)
        if money_provided:
            fin = _compute_item_financials(
                code, rule, amount, unit_price, quantity,
                currency or target.currency or "CNY", exchange_rate,
            )
            target.unit_price = fin["up"] if fin["up"] > 0 else None
            target.quantity = fin["qty"]
            target.amount = fin["amt"]
            target.currency = fin["cur"]
            target.exchange_rate = fin["rate"] if fin["cur"] != "CNY" else None
            target.original_amount = fin["original_amount"]
            target.needs_invoice = fin["needs_invoice"]
            target.is_subsidy = fin["is_subsidy"]
        else:
            # 金额不变，但子类可能变 → 依据现有 CNY 金额/单价重算单据判定
            amt_f = float(target.amount or 0)
            up_f = float(target.unit_price or 0)
            target.needs_invoice = rules.requires_invoice(code, amt_f, up_f)
            target.is_subsidy = rules.is_subsidy(code, amt_f, up_f)

        target.category = rule.category
        target.subtype = code
        target.unit = rule.unit or None
        if description is not None:
            target.description = description or rule.label
        if occur_date:
            target.occur_date = _parse_date(occur_date)
        if from_location is not None:
            target.from_location = from_location or None
        if to_location is not None:
            target.to_location = to_location or None
        if remark is not None:
            target.remark = remark or None
        if attendee_count is not None:
            target.attendee_count = int(attendee_count) if attendee_count else None
        if guest_info is not None:
            target.guest_info = guest_info or None

        await self.db.flush()
        await self._recalc(reimb)
        await self.db.commit()
        logger.info(f"明细已修改: reimb={reimb_id} seq={item_seq} {code} ¥{float(target.amount)}")
        fresh = await self.get(reimb_id)
        fresh_item = next((it for it in fresh.items if it.seq == item_seq), target)
        return fresh, fresh_item

    # -------------------------------------------------------------- 删除明细
    async def remove_item(self, reimb_id: str, item_seq: int) -> Reimbursement:
        reimb = await self.get(reimb_id)
        self._assert_editable(reimb)
        target = next((it for it in reimb.items if it.seq == item_seq), None)
        if not target:
            raise BusinessException(f"未找到序号为 {item_seq} 的明细。", error_code="ITEM_NOT_FOUND")
        await self.db.delete(target)
        await self.db.flush()
        await self._recalc(reimb)
        await self.db.commit()
        return await self.get(reimb_id)

    # ------------------------------------------------------ 为明细关联发票
    async def _assert_invoice_not_duplicate(
        self, invoice_code: str, invoice_number: str,
    ) -> None:
        """发票查重：同一张发票（发票代码 + 发票号码）不得重复登记，杜绝重复报销。

        - 以"发票号码"为主键信号：无号码（手工录入/OCR 失败）时跳过查重。
        - 有发票代码时按（代码, 号码）联合判重；否则仅按号码判重。
        """
        number = (invoice_number or "").strip()
        if not number:
            return
        code = (invoice_code or "").strip()
        conds = [Invoice.invoice_number == number]
        if code:
            conds.append(Invoice.invoice_code == code)
        cnt = (await self.db.execute(
            select(func.count()).select_from(Invoice).where(*conds)
        )).scalar() or 0
        if cnt > 0:
            raise BusinessException(
                f"发票号码 {number} 已被登记过，禁止重复报销。请核对是否为同一张发票。",
                error_code="DUPLICATE_INVOICE",
            )

    async def attach_invoice_to_item(
        self, reimb_id: str, item_seq: int, invoice: dict,
    ) -> Reimbursement:
        reimb = await self.get(reimb_id)
        self._assert_editable(reimb)
        target = next((it for it in reimb.items if it.seq == item_seq), None)
        if not target:
            raise BusinessException(f"未找到序号为 {item_seq} 的明细。", error_code="ITEM_NOT_FOUND")
        # 发票查重（防止同一张发票重复报销）
        await self._assert_invoice_not_duplicate(
            invoice.get("invoice_code"), invoice.get("invoice_number")
        )

        # 发票金额必须真实提供（来自 OCR 或发票原件），系统绝不用明细金额代填，
        # 否则会凭空"造出"一张与明细等额的发票，架空金额铁律。
        inv_amount = _d(invoice.get("amount"))
        if inv_amount <= 0:
            raise BusinessException(
                "请提供发票金额（来自 OCR 识别或发票原件），系统不会自动代填发票金额。",
                error_code="INVOICE_AMOUNT_REQUIRED",
            )

        # 一致性硬校验：该明细已关联发票金额 + 本次发票金额，不得超过明细金额（防超额开票）
        existing_sum = _d(sum(float(v.amount or 0) for v in (target.invoices or [])))
        if existing_sum + inv_amount > _d(target.amount) + Decimal("0.01"):
            raise BusinessException(
                f"发票金额合计 ¥{float(existing_sum + inv_amount):,.2f} 超过明细金额 "
                f"¥{float(target.amount):,.2f}，请核对发票或明细金额。",
                error_code="INVOICE_AMOUNT_MISMATCH",
            )

        tax_amount = _d(invoice.get("tax_amount"))
        total_with_tax = _d(invoice.get("total_with_tax")) if invoice.get("total_with_tax") else inv_amount
        # 发票日期不能晚于今天（明显异常，直接拒绝）
        inv_date = _parse_date(invoice.get("invoice_date"))
        if inv_date and inv_date > date.today():
            raise BusinessException(
                f"发票开票日期 {inv_date.isoformat()} 晚于今天，请核对发票。",
                error_code="INVOICE_DATE_INVALID",
            )
        inv = Invoice(
            reimbursement_id=reimb_id, expense_item_id=target.id,
            invoice_code=invoice.get("invoice_code") or "",
            invoice_number=invoice.get("invoice_number") or "",
            invoice_date=_parse_date(invoice.get("invoice_date")),
            invoice_type=invoice.get("invoice_type") or "",
            seller_name=invoice.get("seller_name") or "",
            buyer_name=invoice.get("buyer_name") or "",
            amount=inv_amount,
            tax_amount=tax_amount,
            total_with_tax=total_with_tax,
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
        提交前严格校验，返回 {ok, errors, warnings, missing_invoices, over_limit}。

        - 大额/必须发票项缺票 → error（阻断提交）。
        - 单价/单日超过费用标准：
            · 未填超标说明(remark) → error（阻断提交，要求补充说明）；
            · 已填超标说明          → warning + over_limit=True（放行，但强制转特殊审批）。
        - 发票金额与明细金额不一致 → warning。
        """
        errors: list[str] = []
        warnings: list[str] = []
        missing_invoices: list[dict] = []
        over_limit = False

        from app.core.config import get_settings
        _settings = get_settings()
        _company_name = (_settings.COMPANY_NAME or "").strip()
        _invoice_max_age = int(getattr(_settings, "INVOICE_MAX_AGE_DAYS", 90) or 90)
        _today = date.today()

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
            # 单价/日限校验（超标准）：硬约束 + 超标说明豁免
            exceeded, eup, limit = rules.exceeds_unit_limit(
                it.subtype, it.unit_price, it.amount, it.quantity
            )
            if exceeded:
                rule = rules.get_subtype(it.subtype)
                unit = ("/" + rule.unit) if (rule and rule.unit) else ""
                if (it.remark or "").strip():
                    over_limit = True
                    warnings.append(
                        f"明细#{it.seq}「{label}」单价 ¥{eup:,.2f} 超过标准 ¥{limit:,.2f}{unit}，"
                        f"已附超标说明：{it.remark}（将转特殊审批）。"
                    )
                else:
                    errors.append(
                        f"明细#{it.seq}「{label}」单价 ¥{eup:,.2f} 超过标准 ¥{limit:,.2f}{unit}，"
                        f"请为该明细填写超标说明(remark)后再提交。"
                    )
            # 数量与出差天数勾稽（餐补天数/住宿晚数不得超过出差天数）
            exceeds_trip, trip_unit = rules.quantity_vs_trip_days(
                it.subtype, it.quantity, reimb.trip_days
            )
            if exceeds_trip:
                errors.append(
                    f"明细#{it.seq}「{label}」数量 {float(it.quantity):g}{trip_unit} 超过出差天数 "
                    f"{reimb.trip_days} 天，请核对出差起止日期或数量。"
                )
            # 招待类：登记招待对象/人数 + 人均标准校验
            if it.subtype in rules.ENTERTAIN_SUBTYPES:
                if not it.attendee_count or int(it.attendee_count) <= 0:
                    warnings.append(
                        f"明细#{it.seq}「{label}」建议登记招待人数(attendee_count)与招待对象(guest_info)，以便核算人均。"
                    )
                else:
                    pp_over, per_person, pp_limit = rules.exceeds_per_person_limit(
                        it.subtype, it.amount, it.attendee_count
                    )
                    if pp_over:
                        if (it.remark or "").strip():
                            over_limit = True
                            warnings.append(
                                f"明细#{it.seq}「{label}」人均 ¥{per_person:,.2f} 超过标准 ¥{pp_limit:,.2f}/人，"
                                f"已附说明：{it.remark}（将转特殊审批）。"
                            )
                        else:
                            errors.append(
                                f"明细#{it.seq}「{label}」人均 ¥{per_person:,.2f} 超过标准 ¥{pp_limit:,.2f}/人"
                                f"（{it.attendee_count}人/¥{float(it.amount):,.2f}），请填写超标说明(remark)后再提交。"
                            )
            # 发票金额与明细金额一致性
            if it.invoices:
                inv_sum = sum(float(v.amount or 0) for v in it.invoices)
                if abs(inv_sum - float(it.amount)) > 0.01:
                    msg = (
                        f"明细#{it.seq}「{label}」发票合计 ¥{inv_sum:,.2f} 与明细金额 "
                        f"¥{float(it.amount):,.2f} 不一致"
                    )
                    # 必须凭票项：发票总额须等于明细金额（硬约束）；否则仅提示
                    if it.needs_invoice:
                        errors.append(msg + "，请补齐/核对发票使两者相等后再提交。")
                    else:
                        warnings.append(msg + "，请核对。")
                # 发票日期与抬头校验
                for v in it.invoices:
                    status = rules.invoice_date_status(v.invoice_date, _today, _invoice_max_age)
                    if status == "future":
                        errors.append(
                            f"明细#{it.seq}「{label}」发票日期 {v.invoice_date.isoformat()} 晚于今天，请核对。"
                        )
                    elif status == "stale":
                        warnings.append(
                            f"明细#{it.seq}「{label}」发票日期 {v.invoice_date.isoformat()} 距今已超过 "
                            f"{_invoice_max_age} 天，可能已过报销时限，需说明原因。"
                        )
                    if _company_name and (v.buyer_name or "").strip() \
                            and _company_name not in v.buyer_name:
                        warnings.append(
                            f"明细#{it.seq}「{label}」发票抬头「{v.buyer_name}」与公司全称"
                            f"「{_company_name}」不一致，请核对。"
                        )

        return {
            "ok": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "missing_invoices": missing_invoices,
            "over_limit": over_limit,
        }

    # ------------------------------------------------------------------ 提交
    async def submit(self, reimb_id: str) -> dict:
        """
        提交报销单：校验 → 预算检查 → 状态置 pending + 初始审批记录。
        返回 {success, reimb_id, need_special_approval, validation, message}。
        """
        reimb = await self.get(reimb_id)
        # 支持"退回后重新提交"：returned 视为可重新提交（会重新占用预算 + 生成新审批链）
        if reimb.status not in ("draft", "returned"):
            return {"success": False, "message": f"报销单已是「{reimb.status}」状态，无需重复提交。"}

        await self._recalc(reimb)
        v = self.validate(reimb)
        if not v["ok"]:
            return {"success": False, "validation": v,
                    "message": "报销单未通过校验，请先补齐必要发票/信息。"}

        # 预算检查（行锁：SELECT ... FOR UPDATE 序列化并发提交，避免读改写竞态超支）
        budget = await self.db.scalar(
            select(DepartmentBudget)
            .where(DepartmentBudget.department == reimb.department)
            .with_for_update()
        )
        if not budget:
            return {"success": False, "message": f"未找到部门「{reimb.department}」的预算配置，请联系财务部。"}

        total = _d(reimb.total_amount)
        remaining = budget.annual_budget - budget.used_amount
        remaining_after = remaining - total
        # 超预算、总额达特殊审批线、或存在"超标准（已附说明）"明细 → 需特殊审批
        need_special = (
            (remaining_after < 0)
            or (float(total) >= rules.SPECIAL_APPROVAL_THRESHOLD)
            or bool(v.get("over_limit"))
        )

        # 预留预算：走状态迁移模型（draft/returned → pending 即 +total），原子自增
        from app.services.reimbursement_svc import seed_approval_chain, apply_status_transition_budget
        await apply_status_transition_budget(self.db, reimb, "pending")
        reimb.budget_remaining_after = remaining_after
        reimb.need_special_approval = need_special
        reimb.status = "pending"

        # 生成两阶段审批链（部门经理 → 财务审批）
        chain = await seed_approval_chain(self.db, reimb)
        await self.db.commit()
        logger.info(f"报销单已提交: {reimb.id} total={float(total)} special={need_special} chain={chain}")
        return {
            "success": True, "reimb_id": reimb.id,
            "total_amount": float(total),
            "invoice_amount": float(reimb.invoice_amount or 0),
            "subsidy_amount": float(reimb.subsidy_amount or 0),
            "need_special_approval": need_special,
            "approval_chain": chain,
            "validation": v,
            "message": "报销单已提交，进入审批流程。"
                       + (f"（审批链：{' → '.join(chain)}）" if chain else ""),
        }

    # ------------------------------------------------------------ 汇总重算
    async def _recalc(self, reimb: Reimbursement) -> None:
        """重算报销单：总额 / 应开票额 / 补贴额 / 已开票额 / 可抵扣税额 / 发票张数。"""
        # 重新载入 items（确保最新）
        items = (await self.db.execute(
            select(ExpenseItem).where(ExpenseItem.reimbursement_id == reimb.id)
        )).scalars().all()
        total = Decimal("0")
        inv_amt = Decimal("0")      # 应开票额（需票明细金额之和）
        sub_amt = Decimal("0")      # 补贴额
        for it in items:
            total += _d(it.amount)
            if it.is_subsidy:
                sub_amt += _d(it.amount)
            else:
                inv_amt += _d(it.amount)
        # 已开票额 / 可抵扣税额：来自实际关联的发票
        inv_row = (await self.db.execute(
            select(
                func.count(),
                func.coalesce(func.sum(Invoice.amount), 0),
                func.coalesce(func.sum(Invoice.tax_amount), 0),
            ).select_from(Invoice).where(Invoice.reimbursement_id == reimb.id)
        )).one()
        inv_count = inv_row[0] or 0
        invoiced_amt = _d(inv_row[1])
        tax_amt = _d(inv_row[2])
        reimb.total_amount = _q(total)
        reimb.invoice_amount = _q(inv_amt)
        reimb.subsidy_amount = _q(sub_amt)
        reimb.invoiced_amount = _q(invoiced_amt)
        reimb.tax_amount = _q(tax_amt)
        reimb.invoice_count = inv_count
        # 依据明细自动推导报销单主费用类型（占比最大者），保证统计/报表口径一致
        if items:
            reimb.expense_type = rules.derive_expense_type(
                [(it.subtype, it.amount) for it in items],
                default=reimb.expense_type or "travel",
            )


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
