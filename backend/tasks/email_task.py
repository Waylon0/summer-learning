"""
=============================================================================
tasks/email_task.py — 异步邮件发送任务
=============================================================================
Celery 任务：后台发送审批通知邮件。

为什么用异步任务？
  发邮件可能耗时 2-5 秒（连接 SMTP 服务器、上传附件）。
  如果在前端请求中同步发送，用户要等 5 秒才能看到"提交成功"。
  用 Celery 异步发送，用户立即得到响应，邮件后台慢慢发。
=============================================================================
"""
from app.core.celery_app import celery_app               # Celery 实例
from loguru import logger


@celery_app.task(name="tasks.send_approval_email")
def send_approval_email_task(
    to_email: str,
    reimb_id: str,
    total_amount: float,
    pdf_path: str = "",
):
    """
    Celery 异步任务：发送审批邮件。

    参数:
        to_email     : 审批人邮箱
        reimb_id     : 报销单 ID
        total_amount : 报销金额
        pdf_path     : PDF 报销单文件路径（可选）

    返回:
        发送结果字典 {"sent": True/False, "reimb_id": "..."}

    使用方式：
      send_approval_email_task.delay("boss@company.com", "abc-123", 1500.00, "/tmp/reimb.pdf")
      ← delay() 是 Celery 的异步调用方法，不会阻塞当前代码
    """
    import asyncio
    from app.services.email_svc import send_email         # 同步邮件服务

    # 构造邮件主题和正文
    subject = f"【报销审批】报销单 {reimb_id} 待审批 - ¥{total_amount:,.2f}"
    body = f"""
    <h2>报销审批通知</h2>
    <p>报销单编号: <b>{reimb_id}</b></p>
    <p>报销金额: <b>¥{total_amount:,.2f}</b></p>
    <p>请登录系统进行审批。</p>
    """

    try:
        # Celery 任务是同步函数，但 send_email 是异步的，
        # 所以用 asyncio.run() 在同步上下文中运行异步函数
        result = asyncio.run(
            send_email(
                to_email,
                subject,
                body,
                pdf_path if pdf_path else None,           # 空字符串视为无附件
                f"报销单_{reimb_id}.pdf",                  # 附件名
            )
        )
        logger.info(f"Email sent to {to_email}: {result}")
        return {"sent": result, "reimb_id": reimb_id}
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return {"sent": False, "error": str(e), "reimb_id": reimb_id}
