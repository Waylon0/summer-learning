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
from app.agent.tools.reimburse_tools import generate_reimbursement_pdf
from app.services.ocr_svc import upload_file, get_file_url


def _reimb_to_pdf_data(reimb: Reimbursement) -> dict:
    """把 Reimbursement ORM 对象（含 invoices/approvals）转成 PDF 生成所需字典。"""
    invoices = []
    for inv in (reimb.invoices or []):
        invoices.append({
            "invoice_code": inv.invoice_code or "",
            "invoice_number": inv.invoice_number or "",
            "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else "",
            "amount": float(inv.amount or 0),
            "tax_amount": float(inv.tax_amount or 0) if inv.tax_amount is not None else 0,
            "seller_name": inv.seller_name or "",
        })
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
        "user_name": reimb.user_name,
        "department": reimb.department,
        "expense_type": reimb.expense_type,
        "total_amount": float(reimb.total_amount or 0),
        "description": reimb.description or "",
        "status": reimb.status,
        "need_special_approval": reimb.need_special_approval,
        "invoices": invoices,
        "approvals": approvals,
    }


async def generate_and_store_reimbursement_pdf(reimb: Reimbursement) -> dict:
    """
    为一张报销单生成结构化 PDF 并存储，返回下载信息。

    Returns:
        {reimb_id, object_name, download_url, total_amount, status}
    Raises:
        Exception: PDF 生成或存储失败时抛出（由调用方决定如何提示）。
    """
    pdf_data = _reimb_to_pdf_data(reimb)

    # CPU 密集：放线程池，避免阻塞事件循环
    pdf_path = await asyncio.to_thread(generate_reimbursement_pdf, pdf_data)
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
