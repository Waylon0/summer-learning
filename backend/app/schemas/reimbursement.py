from pydantic import BaseModel, Field
from decimal import Decimal
from datetime import date, datetime
from typing import Optional


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户输入文本")
    session_id: Optional[str] = Field(None, description="会话ID")
    attachments: Optional[list[str]] = Field(None, description="已上传的票据文件路径列表")


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    intent: Optional[str] = None
    entities: Optional[dict] = None
    tool_calls: Optional[list[dict]] = None


class InvoiceInfo(BaseModel):
    invoice_code: Optional[str] = None
    invoice_number: Optional[str] = None
    amount: Optional[float] = None
    invoice_date: Optional[str] = None
    seller_name: Optional[str] = None
    buyer_name: Optional[str] = None


class ReimbursementCreate(BaseModel):
    user_id: str
    user_name: str
    department: str
    expense_type: str
    description: Optional[str] = None
    invoices: list[InvoiceInfo] = []


class ReimbursementResponse(BaseModel):
    id: str
    user_id: str
    user_name: str
    department: str
    expense_type: str
    total_amount: float
    description: Optional[str]
    invoice_count: int
    need_special_approval: bool
    budget_remaining_after: Optional[float]
    status: str
    created_at: Optional[str]
    updated_at: Optional[str]
    invoices: list[InvoiceInfo] = []
    approvals: list[dict] = []


class BudgetResponse(BaseModel):
    id: str
    department: str
    annual_budget: float
    used_amount: float
    remaining: float
    fiscal_year: int
    usage_rate: float


class ApprovalAction(BaseModel):
    reimbursement_id: str
    approver: str
    action: str = Field(..., description="approve / reject / return")
    comment: Optional[str] = None


class StatusQuery(BaseModel):
    reimbursement_id: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
