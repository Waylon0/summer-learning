import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from app.core.config import get_settings

settings = get_settings()


async def send_email(
    to_email: str,
    subject: str,
    body: str,
    attachment_path: str = None,
    attachment_name: str = None,
) -> bool:
    msg = MIMEMultipart()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html", "utf-8"))

    if attachment_path:
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{attachment_name or "reimbursement.pdf"}"',
            )
            msg.attach(part)

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER or None,
            password=settings.SMTP_PASSWORD or None,
            use_tls=True,
        )
        return True
    except Exception as e:
        print(f"[Email Error] {e}")
        return False
