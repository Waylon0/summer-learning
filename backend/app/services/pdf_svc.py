"""
=============================================================================
app/services/pdf_svc.py — 报销单 PDF 生成服务
=============================================================================
把「结构化报销单 PDF 生成 + 存储」封装为可复用的服务，供:
  - Agent 对话节点 generate_reimbursement_doc
  - REST API POST /reimbursements/{id}/pdf

说明:
  - 发票（invoice）在本系统中仅作为「输入数据」用于 OCR 提取，
    不再由系统生成发票 PDF。
  - 系统生成的是「报销单」这一结构化单据（含申请人/部门/金额/发票明细/审批记录）。
=============================================================================
"""
import asyncio
import os

from loguru import logger

from app.models.reimbursement import Reimbursement
from app.services.reimbursement_pdf import render_reimbursement_pdf
from app.services.ocr_svc import upload_file, get_file_url


def _reimb_to_pdf_data(reimb: Reimbursement) -> dict:
    """把 Reimbursement ORM 对象（含 items/invoices/approvals）转成 PDF 生成所需字典。"""
    from app.agent import expense_rules as rules
    from app.core.config import get_settings
    from collections import defaultdict

    # 明细行（按大类分组）
    items = sorted(reimb.items or [], key=lambda x: x.seq)
    cat_groups: dict[str, list] = defaultdict(list)
    cat_subtotal: dict[str, float] = defaultdict(float)
    # 报销单抬头 = 报销主体公司（发票购买方 buyer_name）；取不到则用配置的公司全称。
    # 注意：绝不能用 seller_name（那是供应商），否则抬头会变成航司/酒店等第三方。
    company_name = ""
    for it in items:
        cat_subtotal[it.category] += float(it.amount or 0)
        invs = [{
            "invoice_code": v.invoice_code or "",
            "invoice_number": v.invoice_number or "",
            "invoice_date": v.invoice_date.isoformat() if v.invoice_date else "",
            "amount": float(v.amount or 0),
            "seller_name": v.seller_name or "",
        } for v in (it.invoices or [])]
        if not company_name:
            for v in (it.invoices or []):
                if (v.buyer_name or "").strip():
                    company_name = v.buyer_name.strip()
                    break
        cat_groups[it.category].append({
            "seq": it.seq,
            "subtype_label": rules.subtype_label(it.subtype),
            "description": it.description or "",
            "unit_price": float(it.unit_price) if it.unit_price is not None else None,
            "quantity": float(it.quantity) if it.quantity is not None else None,
            "unit": it.unit or "",
            "amount": float(it.amount or 0),
            "occur_date": it.occur_date.isoformat() if it.occur_date else "",
            "from_location": it.from_location or "",
            "to_location": it.to_location or "",
            "is_subsidy": it.is_subsidy,
            "needs_invoice": it.needs_invoice,
            "has_invoice": bool(invs),
            "invoices": invs,
        })
    categories = [{
        "category": cat,
        "category_label": rules.category_label(cat),
        "subtotal": round(cat_subtotal[cat], 2),
        "items": cat_groups[cat],
    } for cat in cat_groups]

    approvals = []
    for ap in (reimb.approvals or []):
        approvals.append({
            "step": ap.step,
            "approver": ap.approver,
            "action": ap.action,
            "comment": ap.comment or "",
        })
    return {
        "id": reimb.id,
        "company_name": company_name or get_settings().COMPANY_NAME,
        "user_name": reimb.user_name,
        "department": reimb.department,
        "expense_type": reimb.expense_type,
        "title": reimb.title or "",
        "total_amount": float(reimb.total_amount or 0),
        "invoice_amount": float(reimb.invoice_amount or 0),
        "subsidy_amount": float(reimb.subsidy_amount or 0),
        "description": reimb.description or "",
        "status": reimb.status,
        "need_special_approval": reimb.need_special_approval,
        "trip_destination": reimb.trip_destination or "",
        "trip_start_date": reimb.trip_start_date.isoformat() if reimb.trip_start_date else "",
        "trip_end_date": reimb.trip_end_date.isoformat() if reimb.trip_end_date else "",
        "trip_days": reimb.trip_days,
        "categories": categories,
        "approvals": approvals,
    }


async def generate_and_store_reimbursement_pdf(reimb: Reimbursement) -> dict:
    """
    为一张报销单生成结构化 PDF 并存储，返回下载信息。

    注意：会重新用 ExpenseSheetService 以 eager-load items/invoices/approvals，
    避免异步惰性加载触发 MissingGreenlet。

    Returns:
        {reimb_id, object_name, download_url, total_amount, status}
    Raises:
        Exception: PDF 生成或存储失败时抛出（由调用方决定如何提示）。
    """
    from app.core.database import AsyncSessionLocal
    from app.services.expense_sheet_svc import ExpenseSheetService

    async with AsyncSessionLocal() as db:
        full = await ExpenseSheetService(db).get(reimb.id)
        pdf_data = _reimb_to_pdf_data(full)

    # CPU 密集：放线程池，避免阻塞事件循环
    pdf_path = await asyncio.to_thread(render_reimbursement_pdf, pdf_data)
    try:
        with open(pdf_path, "rb") as f:
            content = f.read()
        object_name = await upload_file(content, os.path.basename(pdf_path), "application/pdf")
        download_url = await get_file_url(object_name)
    finally:
        try:
            os.remove(pdf_path)
        except OSError:
            pass

    logger.info(f"报销单 PDF 已生成: reimb={reimb.id} object={object_name}")
    return {
        "reimb_id": reimb.id,
        "object_name": object_name,
        "download_url": download_url,
        "total_amount": float(reimb.total_amount or 0),
        "status": reimb.status,
    }
