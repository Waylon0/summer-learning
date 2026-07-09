"""
=============================================================================
app/api/v1/invoices.py — 发票台账 API
=============================================================================
  P1  GET  /invoices   发票台账列表页（多维度筛选 + 分页）

说明：发票在本系统中仅作为「输入数据」（上传后由 OCR 提取信息用于报销）。
      系统不生成发票；如需生成结构化单据，请使用 POST /reimbursements/{id}/pdf 生成报销单 PDF。

权限：需登录。台账查询做权限隔离（员工本人 / 经理本部门 / 管理员全部）。
=============================================================================
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.stats_svc import InvoiceLedgerService
from app.schemas.stats import InvoiceListResponse

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("", response_model=InvoiceListResponse)
async def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    date_from: str | None = Query(None, description="YYYY-MM-DD"),
    date_to: str | None = Query(None, description="YYYY-MM-DD"),
    amount_min: float | None = Query(None),
    amount_max: float | None = Query(None),
    expense_type: str | None = Query(None, description="travel/entertainment/office/other"),
    seller_name: str | None = Query(None, description="模糊搜索销售方"),
    keyword: str | None = Query(None, description="模糊搜索发票代码/号码"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """发票台账列表"""
    svc = InvoiceLedgerService(db)
    return await svc.list_invoices(
        page=page,
        page_size=page_size,
        date_from=date_from,
        date_to=date_to,
        amount_min=amount_min,
        amount_max=amount_max,
        expense_type=expense_type,
        seller_name=seller_name,
        keyword=keyword,
        user=user,
    )
