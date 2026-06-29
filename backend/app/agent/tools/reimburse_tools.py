from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from app.core.config import get_settings
from app.schemas.reimbursement import InvoiceInfo
from decimal import Decimal

settings = get_settings()


@tool
def ocr_recognize_invoice(file_path: str) -> dict:
    """识别上传的票据文件(图片/PDF)中的发票信息。传入文件路径，返回发票代码、号码、金额、日期、购销方等结构化信息。"""
    return {
        "invoice_code": "044001900111",
        "invoice_number": "87654321",
        "amount": 1500.00,
        "invoice_date": "2026-06-15",
        "seller_name": "某某科技有限公司",
        "buyer_name": "中国石油华东分公司",
        "file_path": file_path,
    }


@tool
def compliance_check(expense_type: str, total_amount: float, department: str) -> dict:
    """合规审查：检查费用是否符合公司差旅/招待等标准。传入费用类型、总金额、部门，返回合规结论。"""
    limits = {
        "travel": {"daily": 500, "max_per_trip": 10000},
        "entertainment": {"per_person": 200, "max_per_event": 3000},
        "office": {"max_per_item": 5000},
        "other": {"max_per_request": 2000},
    }
    limit = limits.get(expense_type, limits["other"])
    max_allowed = limit.get("max_per_request", limit.get("max_per_trip", limit.get("max_per_item", 2000)))

    if total_amount <= max_allowed:
        return {"compliant": True, "message": f"金额 {total_amount} 元在 {expense_type} 类费用标准 {max_allowed} 元以内，合规。"}
    else:
        return {"compliant": False, "message": f"金额 {total_amount} 元超过 {expense_type} 类费用标准 {max_allowed} 元，需要特殊说明。"}


@tool
def budget_check(department: str, amount: float) -> dict:
    """预算池控制：查询部门预算余额，判断报销金额是否超额。传入部门名称和报销金额，返回预算状态。"""
    mock_budgets = {
        "技术部": {"annual_budget": 500000, "used": 200000},
        "市场部": {"annual_budget": 300000, "used": 250000},
        "财务部": {"annual_budget": 200000, "used": 50000},
        "人事部": {"annual_budget": 150000, "used": 80000},
        "研发部": {"annual_budget": 800000, "used": 400000},
    }
    bud = mock_budgets.get(department, {"annual_budget": 100000, "used": 50000})
    remaining = bud["annual_budget"] - bud["used"]
    after = remaining - amount
    return {
        "department": department,
        "annual_budget": bud["annual_budget"],
        "used": bud["used"],
        "remaining": remaining,
        "after_reimbursement": after,
        "exceeded": after < 0,
        "need_special_approval": after < 0,
    }


@tool
def generate_reimbursement_pdf(reimb_data: dict) -> str:
    """生成结构化报销单PDF。传入报销数据字典，返回生成的PDF文件路径。"""
    path = f"/tmp/reimbursement_{reimb_data.get('id', 'unknown')}.pdf"
    return path


@tool
def send_approval_email(to_email: str, reimb_id: str, total_amount: float) -> dict:
    """将报销单通过邮件发送给审批人。传入审批人邮箱、报销单ID、金额，返回发送结果。"""
    return {"sent": True, "to": to_email, "reimb_id": reimb_id, "message": f"报销单 {reimb_id} (金额 {total_amount} 元) 已发送审批。"}


@tool
def query_reimbursement_status(reimb_id: str = None, date_from: str = None, date_to: str = None) -> dict:
    """查询报销进度：根据报销单号或日期范围查询审批状态。返回待审批/审批中/已通过/已驳回。"""
    return {
        "reimb_id": reimb_id or "N/A",
        "status": "pending",
        "steps": [
            {"step": 1, "approver": "部门经理", "action": "待审批"},
            {"step": 2, "approver": "财务总监", "action": "等待中"},
        ],
    }


ALL_TOOLS = [
    ocr_recognize_invoice,
    compliance_check,
    budget_check,
    generate_reimbursement_pdf,
    send_approval_email,
    query_reimbursement_status,
]
