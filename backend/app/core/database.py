"""
=============================================================================
app/core/database.py — 数据库连接管理
=============================================================================
本文件负责：
  1. 创建数据库引擎（engine）—— 相当于"数据库的遥控器"
  2. 创建会话工厂（AsyncSessionLocal）—— 每次数据库操作都从这里拿一个"对话窗口"
  3. 定义 ORM 基类（Base）—— 所有数据库表的"祖宗类"
  4. 提供 get_db() 依赖注入函数 —— FastAPI 用它自动管理数据库会话的生命周期

小白理解：
  - engine   = 打电话给数据库，建立一条"专线"
  - session  = 每次通话的"话筒"，用完挂断
  - Base     = 所有表的模板，每个具体表都继承它
=============================================================================
"""
from urllib.parse import urlparse
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

# =============================================================================
# 根据数据库类型选择 connect_args（避免 SQLite 收到 PostgreSQL 专用参数）
# =============================================================================
_db_url = settings.DATABASE_URL
_scheme = _db_url.split("://")[0].split("+")[0] if "://" in _db_url else "sqlite"

if _scheme in ("postgresql", "postgres"):
    _connect_args = {
        "timeout": 5,
        "command_timeout": 10,
        "server_settings": {"application_name": "reimburse_agent"},
    }
    _pool_size = 2
    _max_overflow = 5
else:
    # SQLite: check_same_thread=False 是异步访问所必需的
    _connect_args = {"check_same_thread": False}
    _pool_size = 1
    _max_overflow = 3

# =============================================================================
# 1. 创建异步数据库引擎
# =============================================================================
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=_pool_size,
    max_overflow=_max_overflow,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

# =============================================================================
# 2. 创建会话工厂
# =============================================================================
# async_sessionmaker 是一个"会话制造机"，每次调用产生一个新的数据库会话。
#   - expire_on_commit=False : 提交后不使对象过期，方便后续继续使用
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# =============================================================================
# 3. 定义 ORM 基类
# =============================================================================
# 所有数据库表模型都继承自 Base，这样 SQLAlchemy 就知道哪些类是表。
# 例如：class Reimbursement(Base) 表示 Reimbursement 是一张数据库表。
class Base(DeclarativeBase):
    pass


# =============================================================================
# 4. FastAPI 依赖注入 —— 自动管理会话生命周期
# =============================================================================
# FastAPI 的 Depends(get_db) 会在每个请求到来时自动调用这个函数：
#   请求开始 → 创建会话 → 业务代码使用 → 请求结束 → 自动关闭会话
# 这样就不用手动写 session.close()，避免连接泄漏。
async def get_db() -> AsyncSession:
    """FastAPI 依赖注入函数，自动管理数据库会话的创建和关闭。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session        # 把 session 交给业务代码使用
        finally:
            await session.close()  # 无论成功失败，都会关闭会话
