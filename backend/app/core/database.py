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
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

# =============================================================================
# 1. 创建异步数据库引擎
# =============================================================================
# create_async_engine 创建一个能异步操作数据库的引擎对象
#   - echo=DEBUG         : 调试模式下打印所有 SQL 语句（生产环境关掉）
#   - pool_size=10       : 连接池中保持 10 个常备连接（应对并发请求）
#   - max_overflow=20    : 最多额外创建 20 个临时连接（总共 30 个）
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=20,
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
