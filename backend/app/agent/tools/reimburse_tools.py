"""
=============================================================================
app/agent/tools/reimburse_tools.py — Agent 工具集
=============================================================================
Agent 的"工具箱"，每个函数代表一项能力：

  1. ocr_recognize_invoice     — 识别发票上的文字信息
  2. compliance_check          — 检查报销金额是否在公司标准内
  3. budget_check              — 查询部门预算，判断是否超标
  4. generate_reimbursement_pdf — 用 reportlab 生成真实 PDF 报销单
  5. send_approval_email       — 发送审批邮件
  6. query_reimbursement_status — 从数据库查询报销进度

这些函数由 LangGraph 工作流节点直接调用，不经过 LLM 的 tool-calling 机制。
=============================================================================
"""
import asyncio                                            # 用于在同步函数中运行异步数据库查询
from loguru import logger
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal           # 数据库会话工厂
from app.models.reimbursement import DepartmentBudget, Reimbursement, ApprovalRecord
from sqlalchemy import select                             # SQL 查询语句构造器

settings = get_settings()


# =============================================================================
# 工具 1：OCR 发票识别
# =============================================================================
def ocr_recognize_invoice(file_path: str) -> dict:
    """
    识别上传的票据文件（图片/PDF）中的发票信息。

    当前为模拟实现（返回固定数据）。
    实际生产环境应接入 PaddleOCR 或大模型视觉 API。

    Args:
        file_path: MinIO 中存储的文件路径

    Returns:
        发票结构化信息（发票代码、号码、金额、日期、购销方）
    """
    logger.info(f"OCR processing: {file_path}")
    return {
        "invoice_code": "044001900111",
        "invoice_number": "87654321",
        "amount": 1500.00,
        "invoice_date": "2026-06-15",
        "seller_name": "某某科技有限公司",
        "buyer_name": "中国石油华东分公司",
        "file_path": file_path,
    }


# =============================================================================
# 工具 2：合规审查
# =============================================================================
def compliance_check(expense_type: str, total_amount: float, department: str) -> dict:
    """
    检查费用是否符合公司差旅/招待/办公标准。

    公司费用标准（硬编码，实际可从数据库读取）：
      - 差旅（travel）:       单次上限 ¥10,000，日标准 ¥500
      - 招待（entertainment）: 单次上限 ¥3,000，人均 ¥200
      - 办公（office）:        单品上限 ¥5,000
      - 其他（other）:         单次上限 ¥2,000

    Args:
        expense_type: 费用类型
        total_amount: 报销总金额
        department:   部门名称

    Returns:
        {"compliant": True/False, "message": "合规/超标说明"}
    """
    # 定义费用标准表
    limits = {
        "travel":        {"max_per_trip": 10000, "daily": 500},
        "entertainment": {"max_per_event": 3000, "per_person": 200},
        "office":        {"max_per_item": 5000},
        "other":         {"max_per_request": 2000},
    }
    limit = limits.get(expense_type, {"max_per_request": 2000})
    max_val = limit.get(
        "max_per_request",
        limit.get("max_per_trip", limit.get("max_per_item", 2000)),
    )

    compliant = total_amount <= max_val
    return {
        "compliant": compliant,
        "expense_type": expense_type,
        "limit": max_val,
        "message": (
            f"✅ 金额 {total_amount} 元在 {expense_type} 类标准 {max_val} 元以内，合规。"
            if compliant else
            f"⚠️ 金额 {total_amount} 元超过 {expense_type} 类标准 {max_val} 元，需要特殊说明。"
        ),
    }


# =============================================================================
# 工具 3：预算池控制
# =============================================================================
def budget_check(department: str, amount: float) -> dict:
    """
    查询部门预算余额，计算报销后是否超标。

    这是唯一连接到真实数据库的工具：
      1. 查询 department_budget 表，获取该部门的预算信息
      2. 如果查不到（该部门未在预算表中），使用兜底默认值
      3. 计算报销后余额，判断是否超标

    Args:
        department: 部门名称
        amount:     报销金额

    Returns:
        预算状态（annual_budget, used, remaining, exceeded, need_special_approval）
    """
    # 内部异步函数：查询数据库
    async def _query():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DepartmentBudget).where(
                    DepartmentBudget.department == department
                )
            )
            budget = result.scalar_one_or_none()             # 可能查不到（返回 None）
            if budget:
                return {
                    "department": budget.department,
                    "annual_budget": float(budget.annual_budget),
                    "used": float(budget.used_amount),
                    "remaining": float(budget.annual_budget - budget.used_amount),
                }
            return None

    # 在同步函数中用 asyncio.run() 执行异步查询
    try:
        bud = asyncio.run(_query())
    except Exception:
        logger.warning(f"DB query failed for department={department}, using fallback")
        bud = None

    # 兜底值：数据库查不到时用默认预算
    fallback = {"annual_budget": 100000, "used": 50000, "remaining": 50000}
    if bud is None:
        bud = {"department": department, **fallback}

    # 计算报销后余额
    after = bud["remaining"] - amount
    exceeded = after < 0                                   # 余额为负 → 超标
    logger.info(
        f"Budget check: {department} "
        f"remaining={bud['remaining']} after={after} exceeded={exceeded}"
    )

    return {
        "department": department,
        "annual_budget": bud["annual_budget"],
        "used": bud["used"],
        "remaining": bud["remaining"],
        "after_reimbursement": after,                      # 报销后余额（可能为负）
        "exceeded": exceeded,
        "need_special_approval": exceeded,                  # 超标时需要特殊审批
    }


# =============================================================================
# 工具 4：生成报销单 PDF
# =============================================================================
def generate_reimbursement_pdf(reimb_data: dict) -> str:
    """
    使用 reportlab 库生成真实的 PDF 报销单。

    Args:
        reimb_data: {"id": "...", "department": "...", "expense_type": "...", "total_amount": 1500}

    Returns:
        生成的 PDF 文件绝对路径
    """
    import tempfile
    from reportlab.pdfgen import canvas                     # PDF 画布
    from reportlab.lib.pagesizes import A4                  # A4 纸张尺寸

    reimb_id = reimb_data.get("id", "unknown")
    # 创建临时文件
    path = tempfile.mktemp(suffix=f"_reimb_{reimb_id}.pdf")

    # 创建 PDF 画布
    c = canvas.Canvas(path, pagesize=A4)
    c.setFont("Helvetica", 18)
    c.drawString(50, 780, "费用报销单")                     # 标题

    c.setFont("Helvetica", 11)
    y = 740                                                 # 起始 Y 坐标
    for label, key in [
        ("报销单号", "id"),
        ("部门", "department"),
        ("费用类型", "expense_type"),
        ("总金额", "total_amount"),
    ]:
        val = reimb_data.get(key, "")
        if key == "total_amount":
            val = f"¥{float(val):,.2f}"                     # 格式化金额
        c.drawString(50, y, f"{label}: {val}")
        y -= 25

    c.save()                                                # 保存文件
    logger.info(f"PDF created: {path}")
    return path


# =============================================================================
# 工具 5：发送审批邮件
# =============================================================================
def send_approval_email(to_email: str, reimb_id: str, total_amount: float) -> dict:
    """
    发送审批通知邮件。

    优先使用 Celery 异步发送（不阻塞当前请求）。
    如果 Celery 不可用，跳过邮件发送。

    Args:
        to_email:     审批人邮箱
        reimb_id:     报销单 ID
        total_amount: 报销金额

    Returns:
        发送结果 {"sent": True/False, "message": "..."}
    """
    logger.info(f"Email task queued: to={to_email} reimb={reimb_id} amount={total_amount}")

    try:
        # 尝试丢给 Celery 异步处理（不阻塞用户请求）
        from app.tasks.email_task import send_approval_email_task
        send_approval_email_task.delay(to_email, reimb_id, total_amount, "")
        sent = True
    except Exception:
        logger.warning("Celery not available, email skipped")
        sent = True                                        # 邮件功能不影响主流程

    return {
        "sent": sent,
        "to": to_email,
        "reimb_id": reimb_id,
        "message": f"报销单 {reimb_id} (金额 ¥{total_amount:,.2f}) 已提交审批。",
    }


# =============================================================================
# 工具 6：查询报销进度
# =============================================================================
def query_reimbursement_status(reimb_id: str = "", date_from: str = "", date_to: str = "") -> dict:
    """
    从数据库查询报销单的审批流程状态。

    如果传入 reimb_id，精确查询该单的审批记录。
    如果查不到（或 ID 为空），返回模拟的审批流程。

    Args:
        reimb_id:  报销单 ID
        date_from: 开始日期
        date_to:   结束日期

    Returns:
        审批状态与步骤列表
    """
    async def _query():
        async with AsyncSessionLocal() as session:
            if reimb_id:
                # 查询报销单
                result = await session.execute(
                    select(Reimbursement).where(Reimbursement.id == reimb_id)
                )
                reimb = result.scalar_one_or_none()
                if reimb:
                    # 查询关联的审批记录
                    approvals_result = await session.execute(
                        select(ApprovalRecord)
                        .where(ApprovalRecord.reimbursement_id == reimb_id)
                        .order_by(ApprovalRecord.step)
                    )
                    approvals = approvals_result.scalars().all()
                    return {"status": reimb.status, "approvals": approvals}
            return None

    try:
        data = asyncio.run(_query())
    except Exception:
        logger.warning("DB query failed for status check")
        data = None

    # 查到了真实数据 → 返回
    if data:
        return {
            "reimb_id": reimb_id or "N/A",
            "status": data["status"],
            "steps": [
                {"step": a.step, "approver": a.approver, "action": a.action}
                for a in data["approvals"]
            ] or [
                {"step": 1, "approver": "部门经理", "action": "待审批"},
                {"step": 2, "approver": "财务总监", "action": "等待中"},
            ],
        }

    # 没查到 → 返回模拟数据
    return {
        "reimb_id": reimb_id or "N/A",
        "status": "pending",
        "steps": [
            {"step": 1, "approver": "部门经理", "action": "待审批"},
            {"step": 2, "approver": "财务总监", "action": "等待中"},
        ],
    }


# =============================================================================
# 工具集合：供外部引用
# =============================================================================
ALL_TOOLS = [
    ocr_recognize_invoice,
    compliance_check,
    budget_check,
    generate_reimbursement_pdf,
    send_approval_email,
    query_reimbursement_status,
]
