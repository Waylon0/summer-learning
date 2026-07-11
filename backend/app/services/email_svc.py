"""
=============================================================================
app/services/email_svc.py — 邮件发送服务
=============================================================================
使用 aiosmtplib 异步发送邮件（不阻塞主线程）。
支持 SMTP 多种认证方式（STARTTLS / SSL），自动回退。
=============================================================================
"""
import os
import ssl
import asyncio
import smtplib
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
    attachment_bytes: bytes = None,
) -> bool:
    """
    发送邮件（自动选择最优认证方式）。

    附件二选一：
      - attachment_bytes：直接传附件二进制（如从 MinIO/本地存储取出的 PDF 内容），推荐；
      - attachment_path ：本地文件路径（兼容旧用法）。

    关于收件人：SMTP 账号只是【认证发件人】（From，固定为公司账号），
    收件人 to_email 可以是【任意】邮箱 —— 一个 SMTP 账号可给无数不同用户发信。

    Returns:
        True=成功, False=失败（失败仅记录日志，绝不抛异常打断业务）
    """
    from_addr = settings.SMTP_FROM or settings.SMTP_USER or "noreply@company.com"

    msg = MIMEMultipart()
    msg["From"] = from_addr
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "html", "utf-8"))

    # 附件：优先用字节内容，其次本地文件
    _fname = attachment_name or "reimbursement.pdf"
    if attachment_bytes:
        part = MIMEApplication(attachment_bytes, _subtype="pdf", name=_fname)
        part.add_header("Content-Disposition", "attachment", filename=_fname)
        msg.attach(part)
    elif attachment_path and os.path.exists(attachment_path):
        with open(attachment_path, "rb") as f:
            part = MIMEApplication(f.read(), _subtype="pdf", name=_fname)
            part.add_header("Content-Disposition", "attachment", filename=_fname)
            msg.attach(part)

    username = settings.SMTP_USER or None
    password = settings.SMTP_PASSWORD or None

    if not username or not password:
        logger.warning("SMTP credentials not configured — email will be skipped silently")
        return False

    # From 与认证账号域名不一致 → 多数服务商（QQ/Outlook）会拒信，给出告警
    if "@" in from_addr and "@" in username and \
            from_addr.rsplit("@", 1)[-1].lower() != username.rsplit("@", 1)[-1].lower():
        logger.warning(
            f"SMTP_FROM({from_addr}) 与 SMTP_USER({username}) 域名不一致，"
            f"多数邮箱会拒信；建议把 .env 的 SMTP_FROM 设为与 SMTP_USER 相同。"
        )

    # 逐策略尝试
    last_err = ""
    for strategy, kwargs in _build_strategies(username, password):
        try:
            await aiosmtplib.send(msg, **kwargs)
            logger.info(f"Email sent to {to_email} (strategy={strategy})")
            return True
        except Exception as e:
            err_msg = str(e)
            last_err = f"{strategy}: {err_msg}"
            low = err_msg.lower()
            # 认证失败：换端口也无济于事，直接提示并停止
            if "535" in err_msg or "authentication" in low \
                    or "username and password not accepted" in low:
                logger.error(
                    f"SMTP 认证失败（{strategy}）: {e}\n"
                    f"  → QQ 邮箱：需在「设置→账户→POP3/SMTP服务」开启，并用生成的【授权码】"
                    f"作为 SMTP_PASSWORD（不是登录密码）；\n"
                    f"  → Outlook/Office365：启用 SMTP AUTH 或使用应用密码；\n"
                    f"  → 确认 SMTP_FROM 与 SMTP_USER 一致。"
                )
                return False
            logger.warning(f"SMTP {strategy} failed: {e}")

    # 兜底：标准库 smtplib（放线程池，避免阻塞事件循环）。
    # 之所以需要它：Windows 默认的 ProactorEventLoop 与 aiosmtplib 的隐式 SSL(465)
    # 组合，在 TLS 握手阶段常抛 "Unexpected EOF received"（Linux/Docker 无此问题）；
    # 而标准库 smtplib 用同步套接字握手不受该 event-loop bug 影响，凭据/端口相同即可发出。
    try:
        ok = await asyncio.to_thread(_send_via_smtplib, msg, username, password, to_email)
        if ok:
            return True
    except Exception as e:
        last_err = f"{last_err} | smtplib-fallback: {e}"
        logger.warning(f"SMTP smtplib 兜底失败: {e}")

    logger.error(
        f"All SMTP strategies failed for {to_email}. 最后错误：{last_err}\n"
        f"  → 'Unexpected EOF'/SSL 握手错误多为端口与加密方式不匹配、SMTP 服务未开启、"
        f"或使用了登录密码而非授权码。\n"
        f"  → QQ 推荐：SMTP_HOST=smtp.qq.com，SMTP_PORT=465，SMTP_PASSWORD=授权码；"
        f"或 SMTP_PORT=587。请先在 QQ 邮箱开启 SMTP 服务。"
    )
    return False


def _send_via_smtplib(msg, username: str, password: str, to_email: str) -> bool:
    """用标准库 smtplib 同步发信（在线程池中调用）。按配置端口选择 SSL/STARTTLS，
    失败自动回退另一常用端口。仅作 aiosmtplib 失败后的兜底，成功返回 True。"""
    host = settings.SMTP_HOST
    port = settings.SMTP_PORT or 465

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    def _ssl(p: int) -> bool:
        with smtplib.SMTP_SSL(host, p, timeout=30, context=ctx) as s:
            s.login(username, password)
            s.send_message(msg)
        return True

    def _starttls(p: int) -> bool:
        with smtplib.SMTP(host, p, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ctx)
            s.ehlo()
            s.login(username, password)
            s.send_message(msg)
        return True

    if port == 587:
        strategies = [("starttls-587", lambda: _starttls(587)), ("ssl-465", lambda: _ssl(465))]
    elif port == 25:
        strategies = [("starttls-25", lambda: _starttls(25)), ("ssl-465", lambda: _ssl(465))]
    else:
        strategies = [("ssl-465", lambda: _ssl(port)), ("starttls-587", lambda: _starttls(587))]

    last_err = ""
    for name, fn in strategies:
        try:
            fn()
            logger.info(f"Email sent to {to_email} (strategy={name}, via=smtplib)")
            return True
        except Exception as e:
            last_err = f"{name}: {e}"
            low = str(e).lower()
            if "535" in str(e) or "authentication" in low or "not accepted" in low:
                logger.error(f"SMTP 认证失败（smtplib {name}）: {e}")
                return False
            logger.warning(f"smtplib {name} failed: {e}")
    if last_err:
        logger.warning(f"smtplib 全部策略失败: {last_err}")
    return False


def _build_strategies(username: str, password: str):
    """按【配置端口对应的加密方式】构建 SMTP 连接策略，并自动回退到另一常用端口。

    关键：显式设置 use_tls / start_tls，避免二者冲突（这正是 QQ:465 报
    'Unexpected EOF received' 的常见原因）：
      - 465 端口 → 隐式 SSL：use_tls=True,  start_tls=False
      - 587 端口 → STARTTLS：use_tls=False, start_tls=True
      - 25  端口 → STARTTLS / 明文
    并附带宽松的 TLS 上下文（部分服务商证书链/主机名校验会导致握手失败）。
    """
    host = settings.SMTP_HOST
    port = settings.SMTP_PORT or 465

    # 宽松 TLS 上下文：先关主机名校验，再关证书校验（顺序不能反）
    tls_context = ssl.create_default_context()
    tls_context.check_hostname = False
    tls_context.verify_mode = ssl.CERT_NONE
    tls_context.minimum_version = ssl.TLSVersion.TLSv1_2

    base = {"hostname": host, "username": username, "password": password,
            "tls_context": tls_context, "timeout": 30}

    def ssl_(p):
        return (f"ssl-{p}", {**base, "port": p, "use_tls": True, "start_tls": False})

    def starttls_(p):
        return (f"starttls-{p}", {**base, "port": p, "use_tls": False, "start_tls": True})

    def plain_(p):
        return (f"plain-{p}", {**base, "port": p, "use_tls": False, "start_tls": False})

    if port == 465:
        order = [ssl_(465), starttls_(587)]
    elif port == 587:
        order = [starttls_(587), ssl_(465)]
    elif port == 25:
        order = [starttls_(25), plain_(25), ssl_(465)]
    else:
        order = [starttls_(port), ssl_(port), ssl_(465), starttls_(587)]

    seen = set()
    for name, kw in order:
        key = (kw["port"], kw["use_tls"], kw["start_tls"])
        if key in seen:
            continue
        seen.add(key)
        yield name, kw
