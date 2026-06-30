"""初始化数据库：建表 + 种子数据"""
import asyncio
from decimal import Decimal

from app.core.config import get_settings
from app.core.database import Base, engine
from app.models import Reimbursement, Invoice, DepartmentBudget, ApprovalRecord
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


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Tables created.")

    async with AsyncSessionLocal() as session:
        for b in SEED_BUDGETS:
            existing = await session.execute(
                DepartmentBudget.__table__.select().where(
                    DepartmentBudget.department == b["department"]
                )
            )
            if existing.first() is None:
                session.add(DepartmentBudget(**b))
        await session.commit()
    print("Seed data inserted.")

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
