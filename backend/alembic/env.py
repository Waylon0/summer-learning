"""
=============================================================================
alembic/env.py — 数据库迁移环境配置
=============================================================================
Alembic 是 SQLAlchemy 官方的数据库迁移工具。

作用：当数据库表结构发生变更时（如增加字段、修改类型），
Alembic 能自动生成迁移脚本并执行，而不是手动删表重建。

使用方式：
  # 生成迁移脚本（自动检测 ORM 模型的变化）
  uv run alembic revision --autogenerate -m "描述"

  # 执行迁移（将变更应用到数据库）
  uv run alembic upgrade head

  # 回滚到上一个版本
  uv run alembic downgrade -1
=============================================================================
"""
from logging.config import fileConfig
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine     # 异步引擎（支持 asyncpg/aiosqlite）
from alembic import context
import asyncio

from app.core.config import get_settings
from app.core.database import Base                        # ORM 基类（包含所有表的元数据）
from app.models import Reimbursement, Invoice, DepartmentBudget, ApprovalRecord  # 确保所有模型被导入

# ---- Alembic Config 对象 ----
config = context.config
settings = get_settings()

# 设置数据库连接 URL（从配置中读取）
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# 读取 alembic.ini 中的日志配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 需要追踪的表的元数据（Base.metadata 包含所有继承自 Base 的表）
target_metadata = Base.metadata


def run_migrations_offline():
    """
    离线模式：生成 SQL 脚本但不连接数据库。
    适用场景：生成 SQL 文件给 DBA 手动执行。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,                               # 把 Python 值直接写入 SQL（而不是用占位符）
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """在给定的数据库连接上执行迁移"""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    """
    在线模式：直接连接数据库执行迁移。
    使用异步引擎支持 PostgreSQL（asyncpg）和 SQLite（aiosqlite）。
    """
    connectable = create_async_engine(
        settings.DATABASE_URL,
        poolclass=pool.NullPool,                          # 不使用连接池（迁移是单次操作）
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)      # 在同步上下文中运行迁移
    await connectable.dispose()


# ---- 判断运行模式 ----
if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
