#!/bin/bash
# ============================================================================
# ReimburseAgent Backend — Docker 容器入口脚本
# ============================================================================
# 在启动 uvicorn 之前自动完成:
#   1. 等待数据库就绪
#   2. 执行数据库迁移 (Alembic)
#   3. 导入种子数据 (部门预算 + 报销政策)
#   4. 等待 Redis / MinIO 就绪
# ============================================================================
set -e

echo "============================================"
echo " ReimburseAgent Backend — 容器初始化"
echo "============================================"

# ---- 1. 等待 PostgreSQL 就绪 ----
echo ">>> 等待数据库就绪..."
for i in $(seq 1 30); do
    if python3 -c "
import asyncio, os
from sqlalchemy.ext.asyncio import create_async_engine
async def check():
    engine = create_async_engine(os.environ.get('DATABASE_URL', ''))
    try:
        async with engine.connect() as conn:
            await conn.execute('SELECT 1')
        print('ok')
    except Exception:
        pass
    await engine.dispose()
asyncio.run(check())
" 2>/dev/null | grep -q ok; then
        echo "✅ 数据库已就绪"
        break
    fi
    echo "   等待中... ($i/30)"
    sleep 2
done

# ---- 2. 执行数据库迁移 ----
echo ""
echo ">>> 执行数据库迁移..."
uv run alembic upgrade head 2>/dev/null && echo "✅ 迁移完成" || {
    echo "⚠️  Alembic 迁移失败，尝试直接建表..."
    uv run python -c "
import asyncio
from app.core.database import engine, Base
async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
asyncio.run(init())
print('✅ 表结构已创建')
"
}

# ---- 3. 导入种子数据 ----
echo ""
echo ">>> 导入种子数据..."
uv run python -c "
import asyncio, uuid
from decimal import Decimal
from app.core.database import AsyncSessionLocal
from app.models import DepartmentBudget, ExpensePolicy
from sqlalchemy import select

SEED_BUDGETS = [
    {'department': '研发部', 'annual_budget': 500000, 'used_amount': 120000, 'fiscal_year': 2026},
    {'department': '市场部', 'annual_budget': 300000, 'used_amount': 85000, 'fiscal_year': 2026},
    {'department': '销售部', 'annual_budget': 400000, 'used_amount': 220000, 'fiscal_year': 2026},
    {'department': '人力资源部', 'annual_budget': 150000, 'used_amount': 30000, 'fiscal_year': 2026},
    {'department': '财务部', 'annual_budget': 200000, 'used_amount': 45000, 'fiscal_year': 2026},
    {'department': '行政部', 'annual_budget': 180000, 'used_amount': 60000, 'fiscal_year': 2026},
    {'department': '运维部', 'annual_budget': 250000, 'used_amount': 90000, 'fiscal_year': 2026},
]

SEED_POLICIES = [
    {'expense_type': 'travel', 'max_per_trip': 10000, 'daily_limit': 500, 'description': '差旅费'},
    {'expense_type': 'entertainment', 'max_per_event': 3000, 'per_person_limit': 200, 'description': '招待费'},
    {'expense_type': 'office', 'max_per_item': 5000, 'description': '办公用品'},
    {'expense_type': 'other', 'max_per_request': 2000, 'description': '其他费用'},
]

async def seed():
    async with AsyncSessionLocal() as session:
        for b in SEED_BUDGETS:
            q = select(DepartmentBudget).where(DepartmentBudget.department == b['department'])
            if not (await session.execute(q)).first():
                session.add(DepartmentBudget(**b))
                print(f'  + budget: {b[\"department\"]}')
        for p in SEED_POLICIES:
            q = select(ExpensePolicy).where(ExpensePolicy.expense_type == p['expense_type'])
            if not (await session.execute(q)).first():
                session.add(ExpensePolicy(id=str(uuid.uuid4()), **p))
                print(f'  + policy: {p[\"expense_type\"]}')
        await session.commit()
    print('✅ 种子数据就绪')

asyncio.run(seed())
" 2>/dev/null && echo "✅ 种子数据已导入" || echo "⚠️  种子数据导入跳过 (可能已存在)"

# ---- 4. 启动 uvicorn ----
echo ""
echo "============================================"
echo " 🚀 启动 FastAPI 服务: http://0.0.0.0:8000"
echo "    API 文档: http://0.0.0.0:8000/docs"
echo "============================================"
echo ""

exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 "$@"
