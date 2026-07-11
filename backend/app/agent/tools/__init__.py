"""
=============================================================================
app/agent/tools/__init__.py — 工具包导出 + LLM 工具描述
=============================================================================
ALL_TOOLS       : 8 个底层工具函数列表
TOOL_DESCRIPTIONS : LLM function-calling 工具定义
=============================================================================
"""
from app.agent.tools.reimburse_tools import (
    ocr_recognize_invoice,
    compliance_check,
    budget_check,
    generate_reimbursement_pdf,
    send_approval_email,
    save_reimbursement_to_db,
    query_reimbursement_status,
    get_current_user_info,
    ALL_TOOLS,
)

# LLM function-calling 工具描述
TOOL_DESCRIPTIONS = [
    {
        "name": "ocr_recognize_invoice",
        "description": "识别上传的票据文件（图片/PDF），提取发票代码、号码、金额、日期、销售方等信息。参数 file_path 为 MinIO 中的对象路径。",
        "parameters": {"file_path": "string — MinIO 存储路径"},
    },
    {
        "name": "compliance_check",
        "description": "检查报销金额是否符合公司费用标准（差旅/招待/办公/其他），返回是否合规和限额信息。",
        "parameters": {"expense_type": "string", "total_amount": "float", "department": "string"},
    },
    {
        "name": "budget_check",
        "description": "查询部门的年度预算余额，判断本次报销是否超标。",
        "parameters": {"department": "string", "amount": "float"},
    },
    {
        "name": "generate_reimbursement_pdf",
        "description": "生成标准化的中文报销单 PDF 文件，包含公司抬头、基本信息、发票明细、签字区。",
        "parameters": {"reimb_data": "dict — 报销单信息"},
    },
    {
        "name": "send_approval_email",
        "description": "将报销单 PDF 作为附件发送审批邮件给相关负责人。",
        "parameters": {"to_email": "string", "reimb_id": "string", "total_amount": "float", "pdf_path": "string"},
    },
    {
        "name": "save_reimbursement_to_db",
        "description": "将报销单、发票明细、审批记录持久化到数据库，同步更新部门预算。",
        "parameters": {"department": "string", "expense_type": "string", "total_amount": "float", "invoices": "list", "need_special_approval": "bool", "budget_remaining_after": "float", "description": "string"},
    },
    {
        "name": "query_reimbursement_status",
        "description": "根据报销单号查询审批流转进度和当前状态。适用于知道具体报销单号的场景。",
        "parameters": {"reimb_id": "string", "date_from": "string", "date_to": "string"},
    },
    {
        "name": "get_current_user_info",
        "description": "获取当前登录用户信息（ID、姓名、部门、角色）。当用户说\"我要报销\"时自动调用，用其部门作为默认值。",
        "parameters": {"user_id": "string", "user_name": "string", "department": "string", "role": "string"},
    },
]

__all__ = [
    "ALL_TOOLS", "TOOL_DESCRIPTIONS",
    "ocr_recognize_invoice", "compliance_check", "budget_check",
    "generate_reimbursement_pdf", "send_approval_email",
    "save_reimbursement_to_db", "query_reimbursement_status",
    "get_current_user_info",
]
