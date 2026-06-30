"""
=============================================================================
app/services/reimbursement_svc.py — 报销业务逻辑层
=============================================================================
本文件是"业务大脑"，包含三个核心服务类：

  1. ReimbursementService  — 报销单的增删改查
  2. BudgetService         — 部门预算查询
  3. ApprovalService       — 审批记录管理

每一层职责分明：
  API 路由     → 接收 HTTP 请求，提取参数
  Service 层   → 执行业务逻辑（本文件）
  Model 层     → 操作数据库表
  Schema 层    → 数据校验

小白理解：
  API 是"前台接待"，Service 是"业务经理"，Model 是"档案柜"。
  前台接了电话，交给经理处理，经理去档案柜翻资料。
=============================================================================
"""
from decimal import Decimal
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload                        # 预加载关联数据，避免 N+1 查询

from app.models.reimbursement import Reimbursement, Invoice, DepartmentBudget, ApprovalRecord
from app.schemas.reimbursement import ReimbursementCreate, InvoiceInfo


# =============================================================================
# 报销单服务
# =============================================================================
class ReimbursementService:
    """报销单的业务逻辑处理"""

    def __init__(self, db: AsyncSession):
        """构造函数：接收一个数据库会话"""
        self.db = db

    async def create(self, data: ReimbursementCreate, invoice_infos: list[InvoiceInfo]) -> Reimbursement:
        """
        创建一条新的报销申请。

        步骤：
          1. 计算所有发票的总额
          2. 查询部门预算余额
          3. 判断是否预算超标（超标则标记 need_special_approval=True）
          4. 写入报销单 + 发票明细
          5. 提交事务
        """
        # --- 步骤1：计算总额 ---
        total = sum(Decimal(str(i.amount or 0)) for i in invoice_infos)

        # --- 步骤2：查询部门预算 ---
        budget = await self.db.scalar(
            select(DepartmentBudget).where(DepartmentBudget.department == data.department)
        )

        # --- 步骤3：预算控制 ---
        need_special = False
        remaining_after = None
        if budget:
            # 计算报销后的剩余预算 = 年度总额 - 已用 - 本次金额
            remaining_after = budget.annual_budget - budget.used_amount - total
            if remaining_after < 0:                         # 剩余为负数 → 超标
                need_special = True
            budget.used_amount += total                     # 更新已使用金额

        # --- 步骤4：创建报销单 ---
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
            status="pending",                              # 初始状态 = 待审批
        )
        self.db.add(reimb)                                   # 加入待提交队列
        await self.db.flush()                                # 立即同步（为了获取自增 ID）

        # --- 步骤4续：逐张写入发票 ---
        for info in invoice_infos:
            inv = Invoice(
                reimbursement_id=reimb.id,                  # 外键关联
                invoice_code=info.invoice_code,
                invoice_number=info.invoice_number,
                amount=Decimal(str(info.amount or 0)),
                seller_name=info.seller_name,
                buyer_name=info.buyer_name,
            )
            self.db.add(inv)

        # --- 步骤5：提交事务 ---
        await self.db.commit()
        return reimb

    async def get_by_id(self, reimb_id: str) -> Reimbursement | None:
        """
        根据报销单 ID 查询详情。
        selectinload 预加载关联的发票和审批记录，避免后续访问时额外查数据库（N+1 问题）。
        """
        result = await self.db.execute(
            select(Reimbursement)
            .options(
                selectinload(Reimbursement.invoices),        # 同时查出发票
                selectinload(Reimbursement.approvals)        # 同时查出审批记录
            )
            .where(Reimbursement.id == reimb_id)
        )
        return result.scalar_one_or_none()                   # 有就返回对象，没有就返回 None

    async def list_by_user(self, user_id: str, limit: int = 50) -> list[Reimbursement]:
        """查询某个用户的所有报销单（按创建时间倒序）"""
        result = await self.db.execute(
            select(Reimbursement)
            .options(selectinload(Reimbursement.invoices), selectinload(Reimbursement.approvals))
            .where(Reimbursement.user_id == user_id)
            .order_by(Reimbursement.created_at.desc())       # 最新的排最前
            .limit(limit)                                    # 最多返回 limit 条
        )
        return list(result.scalars().all())

    async def list_by_status(
        self, status: str = None, start_date: str = None, end_date: str = None, limit: int = 50
    ) -> list[Reimbursement]:
        """按状态/日期范围查询报销单列表（支持组合条件）"""
        conditions = []                                       # 动态构建查询条件
        if status:
            conditions.append(Reimbursement.status == status)
        if start_date:
            conditions.append(Reimbursement.created_at >= start_date)
        if end_date:
            conditions.append(Reimbursement.created_at <= end_date)

        stmt = (
            select(Reimbursement)
            .options(selectinload(Reimbursement.invoices), selectinload(Reimbursement.approvals))
            .where(and_(*conditions) if conditions else True) # 如果有条件就用 AND 组合，否则全查
            .order_by(Reimbursement.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_status(self, reimb_id: str, status: str) -> Reimbursement | None:
        """更新报销单状态"""
        reimb = await self.get_by_id(reimb_id)
        if reimb:
            reimb.status = status
            await self.db.commit()
        return reimb


# =============================================================================
# 部门预算服务
# =============================================================================
class BudgetService:
    """部门预算的业务逻辑"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_department(self, department: str) -> DepartmentBudget | None:
        """查询某个部门的预算信息"""
        return await self.db.scalar(
            select(DepartmentBudget).where(DepartmentBudget.department == department)
        )

    async def list_all(self) -> list[DepartmentBudget]:
        """列出所有部门的预算（按部门名排序）"""
        result = await self.db.execute(
            select(DepartmentBudget).order_by(DepartmentBudget.department)
        )
        return list(result.scalars().all())


# =============================================================================
# 审批服务
# =============================================================================
class ApprovalService:
    """审批记录的业务逻辑"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(self, reimb_id: str, approver: str, action: str, comment: str = None) -> ApprovalRecord:
        """
        记录一条审批操作。

        步骤：
          1. 查出报销单（不存在则报错）
          2. 计算当前审批步骤序号
          3. 写入审批记录
          4. 根据审批结果更新报销单状态
        """
        # --- 步骤1：查出报销单 ---
        reimb = await self.db.get(Reimbursement, reimb_id)
        if not reimb:
            raise ValueError(f"Reimbursement {reimb_id} not found")

        # --- 步骤2：计算步骤序号 ---
        existing = await self.db.execute(
            select(func.count()).select_from(ApprovalRecord)
            .where(ApprovalRecord.reimbursement_id == reimb_id)
        )
        step = existing.scalar() + 1                       # 已有 N 条记录，新步骤就是 N+1

        # --- 步骤3：写入审批记录 ---
        record = ApprovalRecord(
            reimbursement_id=reimb_id,
            approver=approver,
            step=step,
            action=action,
            comment=comment,
        )
        self.db.add(record)

        # --- 步骤4：更新报销单状态 ---
        if action == "approve":
            reimb.status = "approved"                      # 通过
        elif action == "reject":
            reimb.status = "rejected"                      # 驳回
        elif action == "return":
            reimb.status = "returned"                      # 退回修改

        await self.db.commit()
        return record
