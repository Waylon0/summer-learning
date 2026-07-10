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
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)   # 申请人ID（UUID，36位；加索引方便查询）
    user_name: Mapped[str] = mapped_column(String(64), nullable=False)             # 申请人姓名
    department: Mapped[str] = mapped_column(String(64), nullable=False, index=True) # 申请部门

    # --- 报销详情 ---
    expense_type: Mapped[str] = mapped_column(String(32), nullable=False)          # 主费用类型：travel/entertainment/office/other
    title: Mapped[str] = mapped_column(String(128), nullable=True)                 # 报销单标题（如"北京出差报销"）
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=0  # Decimal=精确小数，12位总长，2位小数（明细汇总）
    )
    invoice_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)     # 需发票部分合计（应开票额）
    invoiced_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)    # 已实际关联发票金额合计（已开票额）
    subsidy_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)     # 补贴部分合计（无需发票）
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)         # 可抵扣进项税额合计
    description: Mapped[str] = mapped_column(Text, nullable=True)                  # 报销说明（可空）
    invoice_count: Mapped[int] = mapped_column(Integer, default=0)                 # 发票张数

    # --- 差旅上下文（可空，差旅类填写）---
    trip_destination: Mapped[str] = mapped_column(String(64), nullable=True)       # 出差目的地
    trip_start_date: Mapped[date] = mapped_column(Date, nullable=True)             # 出差起始日
    trip_end_date: Mapped[date] = mapped_column(Date, nullable=True)              # 出差结束日
    trip_days: Mapped[int] = mapped_column(Integer, nullable=True)                # 出差天数

    # --- 预算控制 ---
    need_special_approval: Mapped[bool] = mapped_column(Boolean, default=False)     # 是否需要特殊审批（预算超标时为True）
    budget_remaining_after: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=True              # 报销后部门剩余预算
    )

    # --- 状态与时间 ---
    status: Mapped[str] = mapped_column(
        String(16), default="draft", index=True     # draft→pending→approved→rejected→returned→paid
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()  # 创建时间（数据库自动填）
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()  # 更新时间
    )

    # --- 关联关系 ---
    # relationship 定义了"一对多"关系：
    #   一个报销单 → 多条费用明细行 → 每行多张发票；一个报销单 → 多条审批记录
    approvals: Mapped[list["ApprovalRecord"]] = relationship(
        back_populates="reimbursement",        # 双向绑定（对方也有一个 reimbursement 字段指向我）
        cascade="all, delete-orphan"           # 删除报销单时，关联的审批记录也一起删掉
    )
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="reimbursement",
        cascade="all, delete-orphan"
    )
    items: Mapped[list["ExpenseItem"]] = relationship(
        back_populates="reimbursement",
        cascade="all, delete-orphan",
        order_by="ExpenseItem.seq",
    )

    # --- 工具方法 ---
    def to_dict(self, with_items: bool = False):
        """把 ORM 对象转成 Python 字典，方便 JSON 序列化"""
        d = {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "department": self.department,
            "expense_type": self.expense_type,
            "title": self.title or "",
            "total_amount": float(self.total_amount or 0),   # Decimal → float 才能 JSON 序列化
            "invoice_amount": float(self.invoice_amount or 0),
            "invoiced_amount": float(self.invoiced_amount or 0),
            "subsidy_amount": float(self.subsidy_amount or 0),
            "tax_amount": float(self.tax_amount or 0),
            "description": self.description,
            "invoice_count": self.invoice_count,
            "trip_destination": self.trip_destination or "",
            "trip_start_date": self.trip_start_date.isoformat() if self.trip_start_date else None,
            "trip_end_date": self.trip_end_date.isoformat() if self.trip_end_date else None,
            "trip_days": self.trip_days,
            "need_special_approval": self.need_special_approval,
            "budget_remaining_after": float(self.budget_remaining_after) if self.budget_remaining_after else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if with_items:
            d["items"] = [it.to_dict() for it in (self.items or [])]
            d["approvals"] = [a.to_dict() for a in (self.approvals or [])]
        return d


# =============================================================================
# 表1b：费用明细行表（报销单 → 多条明细 → 每条明细多张发票）
# =============================================================================
class ExpenseItem(Base):
    """
    费用明细行：报销单里的一笔具体费用。

    真实企业报销单结构：一张报销单下按费用大类列出每一笔明细，
    例如「差旅费」下有：机票 ¥1200（去程）、机票 ¥1180（回程）、
    酒店 ¥500×3晚、餐补 ¥150×4天、打车 ¥45（补贴）……
    每笔明细记录：大类、子类、金额、数量/单价、是否需发票/补贴、发票关联。
    """
    __tablename__ = "expense_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reimbursement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reimbursements.id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)          # 明细顺序

    category: Mapped[str] = mapped_column(String(32), nullable=False)             # 费用大类 transport_intercity...
    subtype: Mapped[str] = mapped_column(String(32), nullable=False)             # 费用子类 flight/train/hotel...
    description: Mapped[str] = mapped_column(String(256), nullable=True)         # 明细说明（如"去程 北京→上海"）

    # 金额构成：unit_price × quantity = amount（均以人民币 CNY 为本位币）
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)   # 单价（如 500 元/晚，CNY）
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=True, default=1)  # 数量（如 3 晚 / 4 天）
    unit: Mapped[str] = mapped_column(String(16), nullable=True)                 # 单位（晚/天/次/程）
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)  # 小计（CNY 本位币）

    # 外币支持（本位币为 CNY；amount 恒为折算后的人民币金额）
    currency: Mapped[str] = mapped_column(String(8), nullable=True, default="CNY")  # 原始币种
    exchange_rate: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=True)   # 汇率（1 外币 = ? CNY）
    original_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=True) # 原币金额（外币时）

    # 单据形式
    evidence_type: Mapped[str] = mapped_column(String(16), default="required")   # required/subsidy/conditional
    is_subsidy: Mapped[bool] = mapped_column(Boolean, default=False)             # 是否作为补贴发放（无需发票）
    needs_invoice: Mapped[bool] = mapped_column(Boolean, default=True)          # 是否必须发票
    has_invoice: Mapped[bool] = mapped_column(Boolean, default=False)           # 是否已提供发票

    # 差旅上下文（可空）
    occur_date: Mapped[date] = mapped_column(Date, nullable=True)                # 发生日期
    from_location: Mapped[str] = mapped_column(String(64), nullable=True)       # 出发地（交通）
    to_location: Mapped[str] = mapped_column(String(64), nullable=True)         # 到达地（交通）

    # 超标说明 / 招待要素等补充信息
    remark: Mapped[str] = mapped_column(Text, nullable=True)                     # 超标说明（超标准明细必填）
    attendee_count: Mapped[int] = mapped_column(Integer, nullable=True)          # 招待人数（招待类）
    guest_info: Mapped[str] = mapped_column(String(256), nullable=True)          # 招待对象/事由（招待类）

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    reimbursement: Mapped["Reimbursement"] = relationship(back_populates="items")
    invoices: Mapped[list["Invoice"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "reimbursement_id": self.reimbursement_id,
            "seq": self.seq,
            "category": self.category,
            "subtype": self.subtype,
            "description": self.description or "",
            "unit_price": float(self.unit_price) if self.unit_price is not None else None,
            "quantity": float(self.quantity) if self.quantity is not None else None,
            "unit": self.unit or "",
            "amount": float(self.amount or 0),
            "currency": self.currency or "CNY",
            "exchange_rate": float(self.exchange_rate) if self.exchange_rate is not None else None,
            "original_amount": float(self.original_amount) if self.original_amount is not None else None,
            "evidence_type": self.evidence_type,
            "is_subsidy": self.is_subsidy,
            "needs_invoice": self.needs_invoice,
            "has_invoice": self.has_invoice,
            "occur_date": self.occur_date.isoformat() if self.occur_date else None,
            "from_location": self.from_location or "",
            "to_location": self.to_location or "",
            "remark": self.remark or "",
            "attendee_count": self.attendee_count,
            "guest_info": self.guest_info or "",
            "invoices": [inv.to_dict() for inv in (self.invoices or [])],
        }


# =============================================================================
# 表2：发票明细表
# =============================================================================
class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reimbursement_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("reimbursements.id"),
        nullable=False, index=True
    )
    expense_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("expense_items.id"), nullable=True, index=True  # 关联到具体费用明细行
    )
    # 发票头部
    invoice_code: Mapped[str] = mapped_column(String(32), nullable=True)
    invoice_number: Mapped[str] = mapped_column(String(32), nullable=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=True)
    invoice_type: Mapped[str] = mapped_column(String(32), nullable=True)
    # 交易双方
    seller_name: Mapped[str] = mapped_column(String(128), nullable=True)
    seller_tax_id: Mapped[str] = mapped_column(String(32), nullable=True)
    buyer_name: Mapped[str] = mapped_column(String(128), nullable=True)
    buyer_tax_id: Mapped[str] = mapped_column(String(32), nullable=True)
    # 金额
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True, default=0)
    total_with_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)
    # 文件
    file_path: Mapped[str] = mapped_column(String(256), nullable=True)

    reimbursement: Mapped["Reimbursement"] = relationship(back_populates="invoices")
    item: Mapped["ExpenseItem"] = relationship(back_populates="invoices")

    def to_dict(self):
        return {
            "id": self.id,
            "reimbursement_id": self.reimbursement_id,
            "expense_item_id": self.expense_item_id or "",
            "invoice_code": self.invoice_code or "",
            "invoice_number": self.invoice_number or "",
            "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
            "invoice_type": self.invoice_type or "",
            "seller_name": self.seller_name or "",
            "seller_tax_id": self.seller_tax_id or "",
            "buyer_name": self.buyer_name or "",
            "buyer_tax_id": self.buyer_tax_id or "",
            "amount": float(self.amount),
            "tax_amount": float(self.tax_amount) if self.tax_amount else 0,
            "total_with_tax": float(self.total_with_tax) if self.total_with_tax else None,
            "file_path": self.file_path or "",
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
    approver: Mapped[str] = mapped_column(String(64), nullable=False)    # 审批人（姓名，最长64）
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


# =============================================================================
# 表5：费用标准配置表
# =============================================================================
class ExpensePolicy(Base):
    """费用报销标准配置（可从管理后台修改，无需重启服务）"""
    __tablename__ = "expense_policy"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    expense_type: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False,
        comment="费用类型: travel/entertainment/office/other"
    )
    max_per_trip: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=True,
        comment="单次上限（差旅）"
    )
    daily_limit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=True,
        comment="日标准（差旅）"
    )
    max_per_event: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=True,
        comment="单次上限（招待）"
    )
    per_person_limit: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=True,
        comment="人均上限（招待）"
    )
    max_per_item: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=True,
        comment="单品上限（办公用品）"
    )
    max_per_request: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=True,
        comment="单次上限（其他）"
    )
    description: Mapped[str] = mapped_column(String(128), nullable=True, comment="费用类型描述")

    def to_dict(self):
        return {
            "id": self.id,
            "expense_type": self.expense_type,
            "max_per_trip": float(self.max_per_trip) if self.max_per_trip else None,
            "daily_limit": float(self.daily_limit) if self.daily_limit else None,
            "max_per_event": float(self.max_per_event) if self.max_per_event else None,
            "per_person_limit": float(self.per_person_limit) if self.per_person_limit else None,
            "max_per_item": float(self.max_per_item) if self.max_per_item else None,
            "max_per_request": float(self.max_per_request) if self.max_per_request else None,
            "description": self.description,
        }
