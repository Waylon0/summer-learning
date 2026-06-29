import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import String, Numeric, Integer, Date, Boolean, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Reimbursement(Base):
    __tablename__ = "reimbursements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_name: Mapped[str] = mapped_column(String(64), nullable=False)
    department: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    expense_type: Mapped[str] = mapped_column(String(32), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    invoice_count: Mapped[int] = mapped_column(Integer, default=0)
    need_special_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    budget_remaining_after: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    approvals: Mapped[list["ApprovalRecord"]] = relationship(back_populates="reimbursement", cascade="all, delete-orphan")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="reimbursement", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "department": self.department,
            "expense_type": self.expense_type,
            "total_amount": float(self.total_amount),
            "description": self.description,
            "invoice_count": self.invoice_count,
            "need_special_approval": self.need_special_approval,
            "budget_remaining_after": float(self.budget_remaining_after) if self.budget_remaining_after else None,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reimbursement_id: Mapped[str] = mapped_column(String(36), ForeignKey("reimbursements.id"), nullable=False, index=True)
    invoice_code: Mapped[str] = mapped_column(String(32), nullable=True)
    invoice_number: Mapped[str] = mapped_column(String(32), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=True)
    seller_name: Mapped[str] = mapped_column(String(128), nullable=True)
    buyer_name: Mapped[str] = mapped_column(String(128), nullable=True)
    file_path: Mapped[str] = mapped_column(String(256), nullable=True)

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


class DepartmentBudget(Base):
    __tablename__ = "department_budget"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    department: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    annual_budget: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    used_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "department": self.department,
            "annual_budget": float(self.annual_budget),
            "used_amount": float(self.used_amount),
            "remaining": float(self.annual_budget - self.used_amount),
            "fiscal_year": self.fiscal_year,
            "usage_rate": float(self.used_amount / self.annual_budget * 100) if self.annual_budget > 0 else 0,
        }


class ApprovalRecord(Base):
    __tablename__ = "approval_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reimbursement_id: Mapped[str] = mapped_column(String(36), ForeignKey("reimbursements.id"), nullable=False, index=True)
    approver: Mapped[str] = mapped_column(String(32), nullable=False)
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=True)
    acted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

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
