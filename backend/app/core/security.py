"""
=============================================================================
app/core/security.py — JWT 认证 + 密码哈希
=============================================================================
直接使用 bcrypt (无 passlib)，避免版本兼容问题。
=============================================================================
"""
import bcrypt
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
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


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: str, username: str, department: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "username": username,
        "department": department,
        "role": role,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None
