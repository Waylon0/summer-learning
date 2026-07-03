"""初始化数据库：建表 + 种子数据"""
import asyncio
import uuid
from decimal import Decimal

from app.core.config import get_settings
from app.core.database import Base, engine
from app.models import Reimbursement, Invoice, DepartmentBudget, ApprovalRecord, ExpensePolicy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

settings = get_settings()

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

SEED_BUDGETS = [
    {"department": "研发部", "annual_budget": 500000, "used_amount": 120000, "fiscal_year": 2026},
    {"department": "市场部", "annual_budget": 300000, "used_amount": 85000, "fiscal_year": 2026},
    {"department": "销售部", "annual_budget": 400000, "used_amount": 220000, "fiscal_year": 2026},
    {"department": "人力资源部", "annual_budget": 150000, "used_amount": 30000, "fiscal_year": 2026},
    {"department": "财务部", "annual_budget": 200000, "used_amount": 45000, "fiscal_year": 2026},
    {"department": "行政部", "annual_budget": 180000, "used_amount": 60000, "fiscal_year": 2026},
    {"department": "运维部", "annual_budget": 250000, "used_amount": 90000, "fiscal_year": 2026},
]

SEED_POLICIES = [
    {
        "expense_type": "travel", "max_per_trip": 10000, "daily_limit": 500,
        "description": "差旅费：单次上限 ¥10,000，日标准 ¥500",
    },
    {
        "expense_type": "entertainment", "max_per_event": 3000, "per_person_limit": 200,
        "description": "招待费：单次上限 ¥3,000，人均 ¥200",
    },
    {
        "expense_type": "office", "max_per_item": 5000,
        "description": "办公用品：单品上限 ¥5,000",
    },
    {
        "expense_type": "other", "max_per_request": 2000,
        "description": "其他费用：单次上限 ¥2,000",
    },
]


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created.")

    async with AsyncSessionLocal() as session:
        # 部门预算种子数据
        for b in SEED_BUDGETS:
            existing = await session.execute(
                DepartmentBudget.__table__.select().where(
                    DepartmentBudget.department == b["department"]
                )
            )
            if existing.first() is None:
                session.add(DepartmentBudget(**b))
                print(f"  + budget: {b['department']}")

        # 费用标准种子数据
        for p in SEED_POLICIES:
            existing = await session.execute(
                ExpensePolicy.__table__.select().where(
                    ExpensePolicy.expense_type == p["expense_type"]
                )
            )
            if existing.first() is None:
                p["id"] = str(uuid.uuid4())
                session.add(ExpensePolicy(**p))
                print(f"  + policy: {p['expense_type']}")

        await session.commit()
    print("Seed data inserted.")

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
