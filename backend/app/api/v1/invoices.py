"""
=============================================================================
app/api/v1/invoices.py — 发票台账 & 发票生成 API
=============================================================================
  P1  GET  /invoices          发票台账列表页（多维度筛选 + 分页）
      POST /invoices/generate 生成模拟增值税发票 PDF（票据），返回下载地址

权限：均需登录。台账查询做权限隔离（员工本人 / 经理本部门 / 管理员全部）。
=============================================================================
"""
import os

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.exceptions import InternalErrorException
from app.models.user import User
from app.services.stats_svc import InvoiceLedgerService
from app.schemas.stats import InvoiceListResponse
from app.schemas.reimbursement import InvoiceGenerateRequest, InvoiceGenerateResponse

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


@router.post("/generate", response_model=InvoiceGenerateResponse)
async def generate_invoice(
    data: InvoiceGenerateRequest,
    user: User = Depends(get_current_user),
):
    """
    生成一张模拟增值税发票 PDF（票据），保存到存储并返回下载地址。

    用途：测试 / 演示 / 补录票据。生成的 object_name 可直接作为
    对话接口 attachments 传入，走 OCR 识别 → 报销流程。

    注意：生成的是「模拟票据」，仅供测试演示，不具备法律效力。
    """
    import asyncio
    from app.agent.tools.reimburse_tools import generate_invoice_pdf
    from app.services.ocr_svc import upload_file, get_file_url

    # 购买方默认用当前登录用户所属公司抬头（保持与系统一致）
    invoice_dict = data.model_dump()
    if not invoice_dict.get("buyer_name"):
        invoice_dict["buyer_name"] = "中国石油华东分公司"

    # 生成 PDF（CPU 密集，放线程池，避免阻塞事件循环）
    # generate_invoice_pdf 会把解析后的实际值（发票号/代码/金额）回写进 invoice_dict
    try:
        pdf_path = await asyncio.to_thread(generate_invoice_pdf, invoice_dict)
    except Exception as e:
        logger.error(f"发票生成失败: {e}")
        raise InternalErrorException(message="发票生成失败", detail={"error": str(e)})

    # 读取并存储到统一存储层（本地 / MinIO）
    try:
        with open(pdf_path, "rb") as f:
            content = f.read()
        filename = os.path.basename(pdf_path)
        object_name = await upload_file(content, filename, "application/pdf")
        download_url = await get_file_url(object_name)
    except Exception as e:
        logger.error(f"发票存储失败: {e}")
        raise InternalErrorException(message="发票存储失败", detail={"error": str(e)})
    finally:
        # 清理临时文件
        try:
            os.remove(pdf_path)
        except OSError:
            pass

    logger.info(f"发票生成成功: user={user.username} object={object_name} total={invoice_dict.get('total_with_tax')}")
    return InvoiceGenerateResponse(
        invoice_number=str(invoice_dict.get("invoice_number") or ""),
        invoice_code=str(invoice_dict.get("invoice_code") or ""),
        object_name=object_name,
        download_url=download_url,
        total_with_tax=float(invoice_dict.get("total_with_tax") or 0),
    )
