from app.core.celery_app import celery_app
from loguru import logger


@celery_app.task(name="tasks.send_approval_email")
def send_approval_email_task(to_email: str, reimb_id: str, total_amount: float, pdf_path: str = ""):
    import asyncio
    from app.services.email_svc import send_email

    subject = f"【报销审批】报销单 {reimb_id} 待审批 - ¥{total_amount:,.2f}"
    body = f"""
    <h2>报销审批通知</h2>
    <p>报销单编号: <b>{reimb_id}</b></p>
    <p>报销金额: <b>¥{total_amount:,.2f}</b></p>
    <p>请登录系统进行审批。</p>
    """
    try:
        result = asyncio.run(send_email(to_email, subject, body, pdf_path if pdf_path else None, f"报销单_{reimb_id}.pdf"))
        logger.info(f"Email sent to {to_email}: {result}")
        return {"sent": result, "reimb_id": reimb_id}
    except Exception as e:
        logger.error(f"Email failed: {e}")
        return {"sent": False, "error": str(e), "reimb_id": reimb_id}
