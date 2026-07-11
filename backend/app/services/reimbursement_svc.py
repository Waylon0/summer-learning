"""
=============================================================================
app/services/reimbursement_svc.py — 报销业务逻辑层（增强版）
=============================================================================
本文件是"业务大脑"，包含三个核心服务类：

  1. ReimbursementService  — 报销单的增删改查
  2. BudgetService         — 部门预算查询
  3. ApprovalService       — 审批记录管理

增强内容（v0.3）：
  - 使用自定义异常替代 ValueError 和裸字符串
  - 关键操作添加详细日志记录
  - 预算创建/更新增加数据库事务保护
=============================================================================
"""
from decimal import Decimal
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from loguru import logger

from app.models.reimbursement import Reimbursement, Invoice, DepartmentBudget, ApprovalRecord
from app.schemas.reimbursement import ReimbursementCreate, InvoiceInfo
from app.core.budget_rules import budget_delta_for_transition
from app.core.approval_rules import build_approval_chain, can_role_approve_step
from app.core.exceptions import (
    ReimbursementNotFoundError,
    BudgetNotFoundError,
    BudgetExceededError,
    ComplianceViolationError,
)


async def seed_approval_chain(db: AsyncSession, reimb: Reimbursement) -> list[str]:
    """为报销单创建两阶段待审批链：每阶段落一条 action='pending' 的占位审批记录
    （approver 暂存该阶段角色标题，如"部门经理""财务审批"）。

    审批推进时逐条把最早的 pending 记录置为 approve/reject/return：阶段一（本部门
    任一经理/超管）通过后进入阶段二（任一财务/超管），两阶段都通过才最终 approved。
    不在此提交事务，由调用方统一 commit。
    """
    chain = build_approval_chain(float(reimb.total_amount or 0), bool(reimb.need_special_approval))
    special = bool(reimb.need_special_approval)
    # 支持"退回后重新提交"：新审批链的步骤序号接续既有记录之后，
    # 既保留历史审批痕迹，又保证本轮 pending 记录为唯一活动链。
    max_step = (await db.execute(
        select(func.coalesce(func.max(ApprovalRecord.step), 0))
        .where(ApprovalRecord.reimbursement_id == reimb.id)
    )).scalar() or 0
    for offset, title in enumerate(chain):
        idx = max_step + offset + 1
        comment = f"等待{title}"
        # 财务阶段（最后一阶段）遇特殊标记时，提示财务审慎复核
        if special and offset == len(chain) - 1:
            comment += "（金额较大/超标/超预算，请审慎复核）"
        db.add(ApprovalRecord(
            reimbursement_id=reimb.id, approver=title, step=idx,
            action="pending", comment=comment,
        ))
    logger.info(f"审批链已生成: reimb={reimb.id} chain={chain} start_step={max_step + 1}")
    return chain


async def adjust_budget_used(db: AsyncSession, department: str, delta: float) -> None:
    """原子调整部门 used_amount（预留/释放通用）。

    - delta > 0：预留额度；delta < 0：释放额度。
    - 用数据库端原子自增，避免"读-改-写"并发覆盖导致预算错乱。
    - 释放后用一条兜底语句把可能出现的负值夹回 0，保证 used_amount 不为负。
    """
    if not department or not delta:
        return
    await db.execute(
        text("UPDATE department_budget SET used_amount = used_amount + :d WHERE department = :dept"),
        {"d": float(delta), "dept": department},
    )
    if delta < 0:
        await db.execute(
            text("UPDATE department_budget SET used_amount = 0 "
                 "WHERE department = :dept AND used_amount < 0"),
            {"dept": department},
        )


async def apply_status_transition_budget(
    db: AsyncSession, reimb: Reimbursement, new_status: str
) -> None:
    """根据报销单状态迁移，联动调整部门预算占用（预留/释放）。

    仅计算并施加增量，不在此提交事务（由调用方统一 commit）。
    """
    delta = budget_delta_for_transition(reimb.status, new_status, float(reimb.total_amount or 0))
    if delta:
        await adjust_budget_used(db, reimb.department, delta)
        logger.info(
            f"预算联动: reimb={reimb.id} dept={reimb.department} "
            f"{reimb.status}→{new_status} used_amount{'+' if delta > 0 else ''}{delta}"
        )


class ReimbursementService:
    """报销单的业务逻辑处理"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: ReimbursementCreate, invoice_infos: list[InvoiceInfo]) -> Reimbursement:
        """
        创建一条新的报销申请。

        完整流程:
          1. 计算发票总额
          2. 查询部门预算 → 不存在则抛 BudgetNotFoundError
          3. 预算检查 → 超标则记录 need_special_approval=True
          4. 写入报销单 + 发票明细
          5. 提交事务（失败自动回滚）

        Raises:
          BudgetNotFoundError: 部门预算信息不存在
        """
        # --- 步骤1：计算总额 ---
        total = sum(Decimal(str(i.amount or 0)) for i in invoice_infos)

        # --- 步骤2：查询部门预算（行锁，避免并发读改写超支）---
        budget = await self.db.scalar(
            select(DepartmentBudget)
            .where(DepartmentBudget.department == data.department)
            .with_for_update()
        )
        if not budget:
            logger.warning(f"预算记录不存在: 部门={data.department}")
            raise BudgetNotFoundError(data.department)

        # --- 步骤3：预算控制 ---
        remaining_after = budget.annual_budget - budget.used_amount - total
        need_special = remaining_after < 0
        if need_special:
            logger.warning(
                f"预算超标: 部门={data.department} "
                f"申请={total} 剩余={budget.annual_budget - budget.used_amount}"
            )
            # 注意：不抛异常 —— 超标只是标记，不阻止提交

        # --- 步骤4：预留预算（原子自增）---
        await adjust_budget_used(self.db, data.department, float(total))

        # --- 步骤5：创建报销单 ---
        reimb = Reimbursement(
            user_id=data.user_id,
            user_name=data.user_name,
            department=data.department,
            expense_type=data.expense_type,
            total_amount=total,
            description=data.description,
            invoice_count=len(invoice_infos),
            need_special_approval=need_special,
            budget_remaining_after=remaining_after,
            status="pending",
        )
        self.db.add(reimb)
        await self.db.flush()

        # --- 步骤6：逐张写入发票（含发票查重，防重复报销）---
        for info in invoice_infos:
            number = (info.invoice_number or "").strip()
            if number:
                code = (info.invoice_code or "").strip()
                conds = [Invoice.invoice_number == number]
                if code:
                    conds.append(Invoice.invoice_code == code)
                dup = (await self.db.execute(
                    select(func.count()).select_from(Invoice).where(*conds)
                )).scalar() or 0
                if dup > 0:
                    from app.core.exceptions import BusinessException
                    raise BusinessException(
                        f"发票号码 {number} 已被登记过，禁止重复报销。",
                        error_code="DUPLICATE_INVOICE",
                    )
            inv = Invoice(
                reimbursement_id=reimb.id,
                invoice_code=info.invoice_code,
                invoice_number=info.invoice_number,
                amount=Decimal(str(info.amount or 0)),
                seller_name=info.seller_name,
                buyer_name=info.buyer_name,
            )
            self.db.add(inv)

        # --- 步骤7：生成两阶段审批链 ---
        await seed_approval_chain(self.db, reimb)

        # --- 步骤8：提交事务 ---
        await self.db.commit()
        logger.info(
            f"报销单已创建: id={reimb.id} "
            f"user={data.user_name} dept={data.department} "
            f"amount={total} special={need_special}"
        )
        return reimb

    async def get_by_id(self, reimb_id: str) -> Reimbursement:
        """
        根据 ID 查询报销单。

        Raises:
          ReimbursementNotFoundError: 报销单不存在
        """
        result = await self.db.execute(
            select(Reimbursement)
            .options(selectinload(Reimbursement.invoices), selectinload(Reimbursement.approvals))
            .where(Reimbursement.id == reimb_id)
        )
        reimb = result.scalar_one_or_none()
        if not reimb:
            logger.warning(f"报销单不存在: {reimb_id}")
            raise ReimbursementNotFoundError(reimb_id)
        return reimb

    async def search(
        self,
        user_id: str = None,
        status: str = None,
        department: str = None,
        expense_type: str = None,
        keyword: str = None,
        amount_min: float = None,
        amount_max: float = None,
        amount_exact: float = None,
        date_from: str = None,
        date_to: str = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Reimbursement], int]:
        """
        多维度综合查询报销单。

        支持维度:
          - 按用户: user_id
          - 按状态: status (pending/approved/rejected/returned/paid/cancelled)
          - 按部门: department
          - 按费用类型: expense_type (travel/entertainment/office/other)
          - 按关键词: keyword → 模糊搜索描述 (ILIKE)
          - 按金额: amount_min / amount_max (范围) 或 amount_exact (精确)
          - 按日期: date_from / date_to
          - 排序: sort_by (created_at/total_amount/department) + sort_dir (asc/desc)
          - 分页: limit + offset

        Returns:
            (报销单列表, 总条数)
        """
        conditions = []
        if user_id:
            conditions.append(Reimbursement.user_id == user_id)
        if status:
            conditions.append(Reimbursement.status == status)
        if department:
            conditions.append(Reimbursement.department == department)
        if expense_type:
            conditions.append(Reimbursement.expense_type == expense_type)
        if keyword:
            conditions.append(Reimbursement.description.ilike(f"%{keyword}%"))
        if amount_exact is not None:
            conditions.append(Reimbursement.total_amount == Decimal(str(amount_exact)))
        else:
            if amount_min is not None:
                conditions.append(Reimbursement.total_amount >= Decimal(str(amount_min)))
            if amount_max is not None:
                conditions.append(Reimbursement.total_amount <= Decimal(str(amount_max)))
        if date_from:
            conditions.append(Reimbursement.created_at >= date_from)
        if date_to:
            conditions.append(Reimbursement.created_at <= date_to)

        # 排序字段白名单（防注入）
        sort_columns = {
            "created_at": Reimbursement.created_at,
            "total_amount": Reimbursement.total_amount,
            "department": Reimbursement.department,
            "status": Reimbursement.status,
            "expense_type": Reimbursement.expense_type,
        }
        sort_col = sort_columns.get(sort_by, Reimbursement.created_at)
        if sort_dir == "asc":
            order_clause = sort_col.asc()
        else:
            order_clause = sort_col.desc()

        base_query = select(Reimbursement).options(
            selectinload(Reimbursement.invoices),
            selectinload(Reimbursement.approvals),
        )
        where_clause = and_(*conditions) if conditions else True

        # 查总数
        count_stmt = select(func.count()).select_from(Reimbursement).where(where_clause)
        total = (await self.db.execute(count_stmt)).scalar()

        # 查数据
        stmt = (
            base_query
            .where(where_clause)
            .order_by(order_clause)
            .offset(offset)
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        reimbs = list(result.scalars().all())

        logger.info(
            f"查询报销单: {len(reimbs)}/{total} 条 "
            f"(filters: user={user_id} status={status} dept={department} "
            f"type={expense_type} kw={keyword} amt={amount_min}-{amount_max} "
            f"sort={sort_by} {sort_dir})"
        )
        return reimbs, total

    async def update_status(self, reimb_id: str, status: str) -> Reimbursement:
        """更新报销单状态"""
        reimb = await self.get_by_id(reimb_id)  # 自带 404 检查
        old_status = reimb.status
        reimb.status = status
        await self.db.commit()
        logger.info(f"报销单状态变更: {reimb_id} {old_status}→{status}")
        return reimb


class BudgetService:
    """部门预算的业务逻辑"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_department(self, department: str) -> DepartmentBudget:
        """
        查询部门预算。

        Raises:
          BudgetNotFoundError: 部门预算不存在
        """
        budget = await self.db.scalar(
            select(DepartmentBudget).where(DepartmentBudget.department == department)
        )
        if not budget:
            logger.warning(f"预算数据不存在: department={department}")
            raise BudgetNotFoundError(department)
        return budget

    async def list_all(self) -> list[DepartmentBudget]:
        """列出所有部门预算"""
        result = await self.db.execute(
            select(DepartmentBudget).order_by(DepartmentBudget.department)
        )
        budgets = list(result.scalars().all())
        return budgets


class ApprovalService:
    """审批记录的业务逻辑"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self, reimb_id: str, approver: str, action: str,
        comment: str = None, approver_role: str = None,
    ) -> ApprovalRecord:
        """
        记录一条审批操作，驱动【两阶段审批状态机】。

        规则:
          - 报销单提交时已生成两阶段待审批链（部门经理、财务审批 两条 pending 占位记录）。
          - approve：把最早一条 pending 记录置为 approve；仅当【两阶段】都通过，
            报销单才 approved；否则保持 pending 等待下一阶段。
          - reject / return：终止流程（rejected / returned），释放已占用预算，
            并把后续未处理的 pending 记录标记为 cancelled。
          - 越权拦截：approver_role 不匹配当前阶段要求的角色则拒绝
            （经理→部门经理阶段、财务→财务阶段、admin 可代签任意阶段）。
          - 同一人不得包办两个阶段（admin 除外）。

        Raises:
          ReimbursementNotFoundError: 报销单不存在
          BusinessException: 动作非法 / 状态非待审批 / 越权 / 同一人包办两阶段
        """
        from app.core.exceptions import BusinessException

        # --- 步骤1：查出报销单 ---
        reimb = await self.db.get(Reimbursement, reimb_id)
        if not reimb:
            logger.warning(f"审批失败: 报销单 {reimb_id} 不存在")
            raise ReimbursementNotFoundError(reimb_id)

        # --- 步骤2：校验 action 合法性 ---
        if action not in {"approve", "reject", "return"}:
            raise BusinessException(
                message=f"无效的审批动作: {action}，有效值: approve/reject/return",
                error_code="INVALID_APPROVAL_ACTION",
            )

        # --- 步骤3：仅"待审批"状态可操作 ---
        if reimb.status != "pending":
            raise BusinessException(
                message=f"报销单当前状态为「{reimb.status}」，仅待审批状态可审批。",
                error_code="NOT_PENDING",
            )

        # --- 步骤4：取出全部审批记录，定位待处理步骤 ---
        rows = list((await self.db.execute(
            select(ApprovalRecord)
            .where(ApprovalRecord.reimbursement_id == reimb_id)
            .order_by(ApprovalRecord.step.asc())
        )).scalars().all())
        pending_rows = [r for r in rows if r.action == "pending"]
        approved_rows = [r for r in rows if r.action == "approve"]

        # 当前待处理步骤（若历史数据无审批链则回退为单级）
        current = pending_rows[0] if pending_rows else None
        step_title = current.approver if current else "部门经理"

        # --- 步骤5：越权拦截（当调用方提供角色时）---
        if approver_role is not None and not can_role_approve_step(approver_role, step_title):
            raise BusinessException(
                message=f"您的角色（{approver_role}）无权审批「{step_title}」步骤。",
                error_code="APPROVAL_FORBIDDEN",
            )

        # --- 步骤6：同一人不得包办两个阶段（admin 除外）---
        if action == "approve" and (approver_role or "").lower() != "admin" \
                and approved_rows and approved_rows[-1].approver == approver:
            raise BusinessException(
                message="同一审批人不能同时包办部门经理与财务两个阶段，请由其他审批人处理下一阶段。",
                error_code="CONSECUTIVE_APPROVAL",
            )

        # 用 Python 端具体时间（而非 func.now() 服务器表达式）：后者会把属性标记为"待刷新"，
        # 返回对象再被 to_dict() 同步访问时会触发异步惰性刷新 → MissingGreenlet。
        now = datetime.now(timezone.utc)

        if action == "approve":
            if current is not None:
                current.action = "approve"
                current.approver = approver
                current.comment = f"[{step_title}] {comment or '审批通过'}"
                current.acted_at = now
                record = current
            else:
                # 历史无审批链：补一条通过记录
                record = ApprovalRecord(
                    reimbursement_id=reimb_id, approver=approver,
                    step=len(rows) + 1, action="approve",
                    comment=comment or "审批通过", acted_at=now,
                )
                self.db.add(record)
            remaining = [r for r in pending_rows if r is not current]
            new_status = "pending" if remaining else "approved"
        else:
            # reject / return：终止本流程
            if current is not None:
                current.action = action
                current.approver = approver
                current.comment = f"[{step_title}] {comment or ('驳回' if action == 'reject' else '退回修改')}"
                current.acted_at = now
                record = current
            else:
                record = ApprovalRecord(
                    reimbursement_id=reimb_id, approver=approver,
                    step=len(rows) + 1, action=action,
                    comment=comment or ("驳回" if action == "reject" else "退回修改"),
                    acted_at=now,
                )
                self.db.add(record)
            # 后续未处理步骤作废
            for r in pending_rows:
                if r is not current:
                    r.action = "cancelled"
                    r.comment = "流程终止（" + ("已驳回" if action == "reject" else "已退回") + "）"
            new_status = "rejected" if action == "reject" else "returned"

        # --- 步骤7：状态迁移 + 预算联动（驳回/退回释放已占用额度）---
        await apply_status_transition_budget(self.db, reimb, new_status)
        reimb.status = new_status

        await self.db.commit()
        logger.info(
            f"审批推进: reimb={reimb_id} step={step_title} "
            f"action={action} approver={approver} → status={new_status}"
        )
        return record

    async def mark_paid(
        self, reimb_id: str, operator: str,
        operator_role: str = None, comment: str = None,
    ) -> ApprovalRecord:
        """出纳付款：已通过(approved) → 已付款(paid)。

        - 权限：仅财务/出纳(finance) 或管理员(admin) 可操作。
        - 预算：approved→paid 均为占用态，预留额度转为实际支出，不再变动 used_amount。

        Raises:
          ReimbursementNotFoundError / BusinessException
        """
        from app.core.exceptions import BusinessException

        reimb = await self.db.get(Reimbursement, reimb_id)
        if not reimb:
            raise ReimbursementNotFoundError(reimb_id)
        if operator_role is not None and (operator_role or "").lower() not in ("finance", "admin"):
            raise BusinessException(
                message="只有财务/出纳可执行付款操作。", error_code="PAYMENT_FORBIDDEN",
            )
        if reimb.status != "approved":
            raise BusinessException(
                message=f"报销单当前状态为「{reimb.status}」，仅已通过(approved)的报销单可付款。",
                error_code="NOT_APPROVED",
            )
        step = (await self.db.execute(
            select(func.count()).select_from(ApprovalRecord)
            .where(ApprovalRecord.reimbursement_id == reimb_id)
        )).scalar() + 1
        record = ApprovalRecord(
            reimbursement_id=reimb_id, approver=operator, step=step,
            action="pay", comment=comment or "出纳已付款", acted_at=datetime.now(timezone.utc),
        )
        self.db.add(record)
        await apply_status_transition_budget(self.db, reimb, "paid")
        reimb.status = "paid"
        await self.db.commit()
        logger.info(f"付款完成: reimb={reimb_id} operator={operator} → paid")
        return record
