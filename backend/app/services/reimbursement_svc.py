from decimal import Decimal
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.reimbursement import Reimbursement, Invoice, DepartmentBudget, ApprovalRecord
from app.schemas.reimbursement import ReimbursementCreate, InvoiceInfo


class ReimbursementService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: ReimbursementCreate, invoice_infos: list[InvoiceInfo]) -> Reimbursement:
        total = sum(Decimal(str(i.amount or 0)) for i in invoice_infos)

        budget = await self.db.scalar(
            select(DepartmentBudget).where(DepartmentBudget.department == data.department)
        )

        need_special = False
        remaining_after = None
        if budget:
            remaining_after = budget.annual_budget - budget.used_amount - total
            if remaining_after < 0:
                need_special = True
            budget.used_amount += total

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

        await self.db.commit()
        return reimb

    async def get_by_id(self, reimb_id: str) -> Reimbursement | None:
        result = await self.db.execute(
            select(Reimbursement)
            .options(selectinload(Reimbursement.invoices), selectinload(Reimbursement.approvals))
            .where(Reimbursement.id == reimb_id)
        )
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: str, limit: int = 50) -> list[Reimbursement]:
        result = await self.db.execute(
            select(Reimbursement)
            .options(selectinload(Reimbursement.invoices), selectinload(Reimbursement.approvals))
            .where(Reimbursement.user_id == user_id)
            .order_by(Reimbursement.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_by_status(
        self, status: str = None, start_date: str = None, end_date: str = None, limit: int = 50
    ) -> list[Reimbursement]:
        conditions = []
        if status:
            conditions.append(Reimbursement.status == status)
        if start_date:
            conditions.append(Reimbursement.created_at >= start_date)
        if end_date:
            conditions.append(Reimbursement.created_at <= end_date)
        stmt = (
            select(Reimbursement)
            .options(selectinload(Reimbursement.invoices), selectinload(Reimbursement.approvals))
            .where(and_(*conditions) if conditions else True)
            .order_by(Reimbursement.created_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_status(self, reimb_id: str, status: str) -> Reimbursement | None:
        reimb = await self.get_by_id(reimb_id)
        if reimb:
            reimb.status = status
            await self.db.commit()
        return reimb


class BudgetService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_department(self, department: str) -> DepartmentBudget | None:
        return await self.db.scalar(
            select(DepartmentBudget).where(DepartmentBudget.department == department)
        )

    async def list_all(self) -> list[DepartmentBudget]:
        result = await self.db.execute(select(DepartmentBudget).order_by(DepartmentBudget.department))
        return list(result.scalars().all())


class ApprovalService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(self, reimb_id: str, approver: str, action: str, comment: str = None) -> ApprovalRecord:
        reimb = await self.db.get(Reimbursement, reimb_id)
        if not reimb:
            raise ValueError(f"Reimbursement {reimb_id} not found")

        existing = await self.db.execute(
            select(func.count()).select_from(ApprovalRecord).where(ApprovalRecord.reimbursement_id == reimb_id)
        )
        step = existing.scalar() + 1

        record = ApprovalRecord(
            reimbursement_id=reimb_id,
            approver=approver,
            step=step,
            action=action,
            comment=comment,
        )
        self.db.add(record)

        if action == "approve":
            reimb.status = "approved"
        elif action == "reject":
            reimb.status = "rejected"
        elif action == "return":
            reimb.status = "returned"

        await self.db.commit()
        return record
