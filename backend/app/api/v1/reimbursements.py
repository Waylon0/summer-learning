"""
=============================================================================
app/api/v1/reimbursements.py — 报销单 CRUD API（增强版）
=============================================================================
增强内容:
  - 使用自定义异常替代手动 raise HTTPException
  - 异常由全局处理器统一捕获并格式化响应
  - 添加详细的操作日志
=============================================================================
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.services.reimbursement_svc import ReimbursementService
from app.schemas.reimbursement import ReimbursementCreate, ReimbursementResponse

router = APIRouter(prefix="/reimbursements", tags=["reimbursements"])


@router.post("", response_model=ReimbursementResponse)
async def create_reimbursement(
    data: ReimbursementCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建报销单 —— 抛出的 BudgetNotFoundError 等由全局异常处理器捕获"""
    svc = ReimbursementService(db)
    logger.info(f"创建报销: user={data.user_name} dept={data.department} type={data.expense_type}")
    reimb = await svc.create(data, data.invoices)
    await db.refresh(reimb, ["invoices", "approvals"])
    return _to_response(reimb)


@router.get("/{reimb_id}", response_model=ReimbursementResponse)
async def get_reimbursement(reimb_id: str, db: AsyncSession = Depends(get_db)):
    """查询单个报销单 —— ReimbursementNotFoundError → 自动返回 404"""
    svc = ReimbursementService(db)
    reimb = await svc.get_by_id(reimb_id)  # 抛异常由全局处理器捕获
    return _to_response(reimb)


@router.get("", response_model=list[ReimbursementResponse])
async def list_reimbursements(
    # 基础筛选
    user_id: str = None,
    status: str = None,
    department: str = None,
    expense_type: str = None,
    # 关键词搜索
    keyword: str = None,
    # 金额筛选
    amount_min: float = None,
    amount_max: float = None,
    amount_exact: float = None,
    # 日期筛选
    date_from: str = None,
    date_to: str = None,
    # 排序与分页
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """
    多维度查询报销单列表。

    查询示例:
      /reimbursements?status=pending&department=技术部
      /reimbursements?amount_min=1000&amount_max=5000
      /reimbursements?amount_exact=1500
      /reimbursements?keyword=上海出差&expense_type=travel
      /reimbursements?date_from=2026-01-01&date_to=2026-12-31
      /reimbursements?sort_by=total_amount&sort_dir=desc&limit=10
    """
    svc = ReimbursementService(db)
    reimbs, total = await svc.search(
        user_id=user_id,
        status=status,
        department=department,
        expense_type=expense_type,
        keyword=keyword,
        amount_min=amount_min,
        amount_max=amount_max,
        amount_exact=amount_exact,
        date_from=date_from,
        date_to=date_to,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )
    return [_to_response(r) for r in reimbs]


def _to_response(reimb) -> ReimbursementResponse:
    """ORM 对象 → Pydantic 响应模型"""
    return ReimbursementResponse(
        id=reimb.id,
        user_id=reimb.user_id,
        user_name=reimb.user_name,
        department=reimb.department,
        expense_type=reimb.expense_type,
        total_amount=float(reimb.total_amount),
        description=reimb.description,
        invoice_count=reimb.invoice_count,
        need_special_approval=reimb.need_special_approval,
        budget_remaining_after=float(reimb.budget_remaining_after) if reimb.budget_remaining_after else None,
        status=reimb.status,
        created_at=reimb.created_at.isoformat() if reimb.created_at else None,
        updated_at=reimb.updated_at.isoformat() if reimb.updated_at else None,
        invoices=[i.to_dict() for i in (reimb.invoices or [])],
        approvals=[a.to_dict() for a in (reimb.approvals or [])],
    )
