"""
=============================================================================
app/services/email_svc.py — 邮件发送服务
=============================================================================
使用 aiosmtplib 异步发送邮件（不阻塞主线程）。

支持：
  - HTML 格式的邮件正文
  - PDF 附件（报销单）

小白理解：调用 send_email() → 自动拼装邮件 → 通过 SMTP 发出去。
=============================================================================
"""
import aiosmtplib                                     # 异步 SMTP 客户端（不阻塞事件循环）
from email.mime.multipart import MIMEMultipart         # 邮件容器（可包含正文+附件）
from email.mime.text import MIMEText                   # 邮件正文（HTML/纯文本）
from email.mime.base import MIMEBase                   # 邮件附件基类
from email import encoders                             # Base64 编码（附件需要编码后传输）
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
    发送一封邮件。

    参数:
        to_email        : 收件人邮箱
        subject         : 邮件主题
        body            : 邮件正文（支持 HTML）
        attachment_path : 附件文件路径（没有则不附加）
        attachment_name : 附件的显示名称

    返回: True=发送成功, False=发送失败

    流程：
      1. 创建 MIMEMultipart 邮件对象
      2. 设置发件人、收件人、主题
      3. 添加 HTML 正文
      4. 如果有附件，读取文件并 Base64 编码后附加
      5. 通过 aiosmtplib 发送（使用 TLS 加密）
    """
    # --- 步骤1-2：创建邮件对象并设置头部 ---
    msg = MIMEMultipart()                              # 邮件容器
    msg["From"] = settings.SMTP_FROM                   # 发件人
    msg["To"] = to_email                               # 收件人
    msg["Subject"] = subject                           # 主题

    # --- 步骤3：添加 HTML 正文 ---
    msg.attach(MIMEText(body, "html", "utf-8"))        # "html" 表示支持 HTML 格式

    # --- 步骤4：添加附件（如果有）---
    if attachment_path:
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")  # 通用二进制类型
            part.set_payload(f.read())                       # 设置附件内容
            encoders.encode_base64(part)                     # Base64 编码
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{attachment_name or "reimbursement.pdf"}"',
            )
            msg.attach(part)

    # --- 步骤5：发送 ---
    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,               # SMTP 服务器
            port=settings.SMTP_PORT,                    # 端口（587=STARTTLS）
            username=settings.SMTP_USER or None,        # 没有用户名就传 None
            password=settings.SMTP_PASSWORD or None,
            use_tls=True,                               # 使用 TLS 加密
        )
        return True
    except Exception as e:
        # 发送失败时打印错误但让程序继续运行
        print(f"[Email Error] {e}")
        return False
