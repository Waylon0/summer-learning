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
from typing import Optional
from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from loguru import logger

from app.models.reimbursement import Reimbursement, Invoice, DepartmentBudget, ApprovalRecord
from app.schemas.reimbursement import ReimbursementCreate, InvoiceInfo
from app.core.exceptions import (
    ReimbursementNotFoundError,
    BudgetNotFoundError,
    BudgetExceededError,
    ComplianceViolationError,
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

        # --- 步骤2：查询部门预算 ---
        budget = await self.db.scalar(
            select(DepartmentBudget).where(DepartmentBudget.department == data.department)
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

        # --- 步骤4：更新预算已使用金额 ---
        budget.used_amount += total

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

        # --- 步骤6：逐张写入发票 ---
        for info in invoice_infos:
            inv = Invoice(
                reimbursement_id=reimb.id,
                invoice_code=info.invoice_code,
                invoice_number=info.invoice_number,
                amount=Decimal(str(info.amount or 0)),
                seller_name=info.seller_name,
                buyer_name=info.buyer_name,
            )
            self.db.add(inv)

        # --- 步骤7：提交事务 ---
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
        self, reimb_id: str, approver: str, action: str, comment: str = None
    ) -> ApprovalRecord:
        """
        记录一条审批操作。

        Raises:
          ReimbursementNotFoundError: 报销单不存在
          BusinessException: 无效的审批动作
        """
        # --- 步骤1：查出报销单 ---
        reimb = await self.db.get(Reimbursement, reimb_id)
        if not reimb:
            logger.warning(f"审批失败: 报销单 {reimb_id} 不存在")
            raise ReimbursementNotFoundError(reimb_id)

        # --- 步骤2：校验 action 合法性 ---
        valid_actions = {"approve", "reject", "return"}
        if action not in valid_actions:
            from app.core.exceptions import BusinessException
            raise BusinessException(
                message=f"无效的审批动作: {action}，有效值: {valid_actions}",
                error_code="INVALID_APPROVAL_ACTION",
            )

        # --- 步骤3：计算步骤序号 ---
        existing = await self.db.execute(
            select(func.count()).select_from(ApprovalRecord)
            .where(ApprovalRecord.reimbursement_id == reimb_id)
        )
        step = existing.scalar() + 1

        # --- 步骤4：写入审批记录 ---
        record = ApprovalRecord(
            reimbursement_id=reimb_id,
            approver=approver,
            step=step,
            action=action,
            comment=comment,
        )
        self.db.add(record)

        # --- 步骤5：更新报销单状态 ---
        status_map = {"approve": "approved", "reject": "rejected", "return": "returned"}
        reimb.status = status_map[action]

        await self.db.commit()
        logger.info(
            f"审批完成: reimb={reimb_id} step={step} "
            f"action={action} approver={approver}"
        )
        return record
