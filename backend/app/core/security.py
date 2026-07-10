"""
=============================================================================
app/core/security.py — JWT 认证 + 密码哈希
=============================================================================
- 密码哈希：直接使用 bcrypt（无 passlib），避免版本兼容问题。
- JWT：使用**标准库自实现的 HS256**（hmac + hashlib + base64 + json），
  不再依赖 python-jose。原因：python-jose 属纯 Python 包，在部分环境里
  出现"已在 lock/已列出却无法 import"的情况，会导致后端无法启动；
  HS256 逻辑简单且标准，用 stdlib 实现最稳，零外部依赖。
=============================================================================
"""
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import bcrypt
from loguru import logger
from app.core.config import get_settings

settings = get_settings()

SECRET_KEY = settings.JWT_SECRET_KEY
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# 使用不安全的开发占位密钥时告警（提醒生产环境务必通过环境变量配置）
if "INSECURE" in SECRET_KEY:
    logger.warning(
        "⚠️  JWT_SECRET_KEY 未配置，正在使用不安全的开发占位密钥！"
        "请在 .env 或环境变量中设置 JWT_SECRET_KEY 后再部署到生产环境。"
    )


# =============================================================================
# 密码哈希
# =============================================================================
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# =============================================================================
# JWT（HS256，标准库实现）
# =============================================================================
def _b64url_encode(raw: bytes) -> str:
    """Base64URL 编码（去除末尾 '=' 填充），符合 JWT 规范。"""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(seg: str) -> bytes:
    """Base64URL 解码（补齐填充）。"""
    pad = "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg + pad)


def _sign(signing_input: bytes) -> bytes:
    return hmac.new(SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()


def create_access_token(user_id: str, username: str, department: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    header = {"alg": ALGORITHM, "typ": "JWT"}
    payload = {
        "sub": user_id,
        "username": username,
        "department": department,
        "role": role,
        "exp": int(expire.timestamp()),
        "iat": int(now.timestamp()),
    }
    seg_header = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    seg_payload = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{seg_header}.{seg_payload}".encode("ascii")
    seg_sig = _b64url_encode(_sign(signing_input))
    return f"{seg_header}.{seg_payload}.{seg_sig}"


def decode_access_token(token: str) -> dict | None:
    """校验签名与过期时间，成功返回 payload，失败返回 None。"""
    try:
        parts = (token or "").split(".")
        if len(parts) != 3:
            return None
        seg_header, seg_payload, seg_sig = parts
        signing_input = f"{seg_header}.{seg_payload}".encode("ascii")
        expected = _sign(signing_input)
        actual = _b64url_decode(seg_sig)
        # 恒定时间比较，防时序攻击
        if not hmac.compare_digest(expected, actual):
            return None
        payload = json.loads(_b64url_decode(seg_payload))
        exp = payload.get("exp")
        if exp is not None and time.time() > float(exp):
            return None  # 已过期
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, KeyError):
        return None
