"""
=============================================================================
app/models/reimbursement.py — 数据库表结构定义（ORM 模型）
=============================================================================
本文件用 SQLAlchemy ORM 定义了 4 张核心业务表：

  1. Reimbursement      — 报销申请单主表（谁申请了多少钱）
  2. Invoice            — 发票明细表（每张发票多少钱）
  3. DepartmentBudget   — 部门预算控制表（每个部门还剩多少钱）
  4. ApprovalRecord     — 审批流转记录表（谁在什么时间批了/拒了）

小白理解：
  这些类就像 Excel 的表头定义。
  每创建一个实例（如 Reimbursement(...)），就相当于在表中插入一行数据。

Mapped 类型标注：
  既是 Python 类型提示，也让 SQLAlchemy 知道这个字段对应数据库的什么列。
=============================================================================
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Numeric, Integer, Date, Boolean, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


# =============================================================================
# 表1：报销申请单主表
# =============================================================================
class Reimbursement(Base):
    __tablename__ = "reimbursements"  # 数据库中表的名字

    # --- 基本信息 ---
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True,               # 主键（唯一标识）
        default=lambda: str(uuid.uuid4())           # 自动生成随机 UUID
    )
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)   # 申请人ID（加索引方便查询）
    user_name: Mapped[str] = mapped_column(String(64), nullable=False)             # 申请人姓名
    department: Mapped[str] = mapped_column(String(64), nullable=False, index=True) # 申请部门

    # --- 报销详情 ---
    expense_type: Mapped[str] = mapped_column(String(32), nullable=False)          # 费用类型：travel/entertainment/office/other
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False             # Decimal=精确小数，12位总长，2位小数
    )
    description: Mapped[str] = mapped_column(Text, nullable=True)                  # 报销说明（可空）
    invoice_count: Mapped[int] = mapped_column(Integer, default=0)                 # 发票张数

    # --- 预算控制 ---
    need_special_approval: Mapped[bool] = mapped_column(Boolean, default=False)     # 是否需要特殊审批（预算超标时为True）
    budget_remaining_after: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=True              # 报销后部门剩余预算
    )

    # --- 状态与时间 ---
    status: Mapped[str] = mapped_column(
        String(16), default="pending", index=True  # pending→approved→rejected→paid
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()  # 创建时间（数据库自动填）
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()  # 更新时间
    )

    # --- 关联关系 ---
    # relationship 定义了"一对多"关系：
    #   一个报销单 → 多张发票、多条审批记录
    approvals: Mapped[list["ApprovalRecord"]] = relationship(
        back_populates="reimbursement",        # 双向绑定（对方也有一个 reimbursement 字段指向我）
        cascade="all, delete-orphan"           # 删除报销单时，关联的审批记录也一起删掉
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="reimbursement",
        cascade="all, delete-orphan"
    )

    # --- 工具方法 ---
    def to_dict(self):
        """把 ORM 对象转成 Python 字典，方便 JSON 序列化"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "department": self.department,
            "expense_type": self.expense_type,
            "total_amount": float(self.total_amount),   # Decimal → float 才能 JSON 序列化
            "description": self.description,
            "invoice_count": self.invoice_count,
            "need_special_approval": self.need_special_approval,
            "budget_remaining_after": float(self.budget_remaining_after) if self.budget_remaining_after else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# =============================================================================
# 表2：发票明细表
# =============================================================================
class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reimbursement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reimbursements.id"),  # 外键：指向报销单的 id
        nullable=False, index=True                     # 加索引加快关联查询
    )
    invoice_code: Mapped[str] = mapped_column(String(32), nullable=True)      # 发票代码
    invoice_number: Mapped[str] = mapped_column(String(32), nullable=True)    # 发票号码
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)   # 发票金额
    invoice_date: Mapped[date] = mapped_column(Date, nullable=True)            # 开票日期
    seller_name: Mapped[str] = mapped_column(String(128), nullable=True)      # 销售方名称
    buyer_name: Mapped[str] = mapped_column(String(128), nullable=True)       # 购买方名称
    file_path: Mapped[str] = mapped_column(String(256), nullable=True)         # MinIO 存储路径

    # 关联：一张发票属于一个报销单
    reimbursement: Mapped["Reimbursement"] = relationship(back_populates="invoices")

    def to_dict(self):
        return {
            "id": self.id,
            "reimbursement_id": self.reimbursement_id,
            "invoice_code": self.invoice_code,
            "invoice_number": self.invoice_number,
            "amount": float(self.amount),
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "seller_name": self.seller_name,
            "buyer_name": self.buyer_name,
            "file_path": self.file_path,
        }


# =============================================================================
# 表3：部门预算控制表
# =============================================================================
class DepartmentBudget(Base):
    __tablename__ = "department_budget"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    department: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False    # unique=True 确保不重名
    )
    annual_budget: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)  # 年度预算总额
    used_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)         # 已使用金额
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)               # 财政年度

    def to_dict(self):
        return {
            "id": self.id,
            "department": self.department,
            "annual_budget": float(self.annual_budget),
            "used_amount": float(self.used_amount),
            "remaining": float(self.annual_budget - self.used_amount),  # 剩余 = 年度总额 - 已用
            "fiscal_year": self.fiscal_year,
            "usage_rate": float(self.used_amount / self.annual_budget * 100) if self.annual_budget > 0 else 0,
        }


# =============================================================================
# 表4：审批流转记录表
# =============================================================================
class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reimbursement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reimbursements.id"),
        nullable=False, index=True
    )
    approver: Mapped[str] = mapped_column(String(32), nullable=False)    # 审批人
    step: Mapped[int] = mapped_column(Integer, nullable=False)            # 审批步骤（1, 2, 3...）
    action: Mapped[str] = mapped_column(String(16), nullable=False)      # 审批动作：approve/reject/return
    comment: Mapped[str] = mapped_column(Text, nullable=True)            # 审批意见
    acted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()               # 审批时间
    )

    # 关联：一条审批记录属于一个报销单
    reimbursement: Mapped["Reimbursement"] = relationship(back_populates="approvals")

    def to_dict(self):
        return {
            "id": self.id,
            "reimbursement_id": self.reimbursement_id,
            "approver": self.approver,
            "step": self.step,
            "action": self.action,
            "comment": self.comment,
            "acted_at": self.acted_at.isoformat() if self.acted_at else None,
        }
