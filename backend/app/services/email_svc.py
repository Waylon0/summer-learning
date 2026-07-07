"""
=============================================================================
app/services/email_svc.py — 邮件发送服务
=============================================================================
使用 aiosmtplib 异步发送邮件（不阻塞主线程）。
支持 SMTP 多种认证方式（STARTTLS / SSL），自动回退。
=============================================================================
"""
import os
import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from loguru import logger
from app.core.config import get_settings

settings = get_settings()


async def send_email(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: str = None,
    attachment_name: str = None,
) -> bool:
    """
    发送邮件（自动选择最优认证方式）。

    Returns:
        True=成功, False=失败
    """
    from_addr = settings.SMTP_FROM or settings.SMTP_USER or "noreply@company.com"

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html", "utf-8"))

    if attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf", name=attachment_name or "reimbursement.pdf")
            part.add_header("Content-Disposition", "attachment", filename=attachment_name or "reimbursement.pdf")
            msg.attach(part)

    username = settings.SMTP_USER or None
    password = settings.SMTP_PASSWORD or None

    if not username or not password:
        logger.warning("SMTP credentials not configured — email will be skipped silently")
        return False

    # 逐策略尝试
    for strategy, kwargs in _build_strategies(username, password):
        try:
            await aiosmtplib.send(msg, **kwargs)
            logger.info(f"Email sent to {to_email} (strategy={strategy})")
            return True
        except Exception as e:
            err_msg = str(e)
            if "535" in err_msg or "authentication" in err_msg.lower():
                logger.error(
                    f"SMTP auth failed ({strategy}): {e}\n"
                    f"  → 如果使用 Outlook/Office365，请在账户设置中启用 SMTP AUTH，"
                    f"或生成应用密码: https://aka.ms/AppPasswords\n"
                    f"  → 如果使用 QQ邮箱，请使用授权码而非登录密码"
                )
                return False
            logger.warning(f"SMTP {strategy} failed: {e}")

    logger.error(f"All SMTP strategies failed for {to_email}")
    return False


def _build_strategies(username: str, password: str):
    """构建尝试的 SMTP 连接策略列表"""
    port = settings.SMTP_PORT or 587
    host = settings.SMTP_HOST

    # Strategy 1: STARTTLS on specified port
    yield ("starttls", {
        "hostname": host, "port": port,
        "username": username, "password": password,
        "start_tls": True,
        "timeout": 15,
    })

    # Strategy 2: SSL on 465 (if port is 587, try 465)
    if port == 587:
        yield ("ssl-465", {
            "hostname": host, "port": 465,
            "username": username, "password": password,
            "use_tls": True,
            "timeout": 15,
        })
