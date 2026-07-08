"""初始化数据库：建表 + 种子数据（含管理员用户）"""
import asyncio
import uuid
from decimal import Decimal

from app.core.config import get_settings
from app.core.database import Base, engine
from app.core.security import hash_password
from app.models import Reimbursement, Invoice, DepartmentBudget, ApprovalRecord, ExpensePolicy, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

settings = get_settings()

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

SEED_USERS = [
    {"username": "admin", "password": "admin123", "name": "系统管理员", "department": "技术部", "role": "admin"},
    {"username": "zhangsan", "password": "123456", "name": "张三", "department": "技术部", "role": "employee"},
    {"username": "lisi", "password": "123456", "name": "李四", "department": "研发部", "role": "employee"},
    {"username": "wangwu", "password": "123456", "name": "王五", "department": "市场部", "role": "employee"},
    {"username": "manager_wang", "password": "123456", "name": "王总监", "department": "技术部", "role": "manager"},
    {"username": "manager_li", "password": "123456", "name": "李总监", "department": "研发部", "role": "manager"},
    {"username": "finance_zhao", "password": "123456", "name": "赵财务", "department": "财务部", "role": "finance"},
]

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
    # ---- 通用类型 ----
    {"expense_type": "travel", "max_per_trip": 10000, "daily_limit": 500,
     "description": "差旅费：单次上限 ¥10,000，住宿日标准 ¥500"},
    {"expense_type": "entertainment", "max_per_event": 3000, "per_person_limit": 200,
     "description": "招待费：单次上限 ¥3,000，人均 ¥200"},
    {"expense_type": "office", "max_per_item": 5000,
     "description": "办公用品：单品上限 ¥5,000"},
    {"expense_type": "communication", "max_per_request": 500,
     "description": "通信费：月度上限 ¥500"},
    {"expense_type": "transport", "max_per_request": 300,
     "description": "市内交通费：单次上限 ¥300"},
    {"expense_type": "meeting", "max_per_request": 8000,
     "description": "会议费：单次上限 ¥8,000"},
    {"expense_type": "training", "max_per_request": 5000,
     "description": "培训费：单次上限 ¥5,000"},
    {"expense_type": "other", "max_per_request": 2000,
     "description": "其他费用：单次上限 ¥2,000"},
    # ---- 部门专属类型 ----
    {"expense_type": "rd_materials", "max_per_request": 20000,
     "description": "研发材料费：单次上限 ¥20,000 (研发部)"},
    {"expense_type": "rd_equipment", "max_per_request": 50000,
     "description": "研发设备费：单次上限 ¥50,000 (研发部)"},
    {"expense_type": "tech_acquisition", "max_per_request": 100000,
     "description": "技术引进费：单次上限 ¥100,000 (技术部)"},
    {"expense_type": "software_license", "max_per_request": 30000,
     "description": "软件许可费：年度上限 ¥30,000 (技术部)"},
    {"expense_type": "advertisement", "max_per_request": 50000,
     "description": "广告推广费：单次上限 ¥50,000 (市场部)"},
    {"expense_type": "exhibition", "max_per_request": 30000,
     "description": "展会费：单次上限 ¥30,000 (市场部)"},
    {"expense_type": "client_maintenance", "max_per_request": 5000,
     "description": "客户维护费：单次上限 ¥5,000 (销售部)"},
    {"expense_type": "audit", "max_per_request": 20000,
     "description": "审计服务费：单次上限 ¥20,000 (财务部)"},
    {"expense_type": "recruitment", "max_per_request": 10000,
     "description": "招聘费：单次上限 ¥10,000 (人事部)"},
    {"expense_type": "renovation", "max_per_request": 50000,
     "description": "办公室装修费：单次上限 ¥50,000 (行政部)"},
    {"expense_type": "cloud_service", "max_per_request": 20000,
     "description": "云服务费：月度上限 ¥20,000 (运维部)"},
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
    print("Seed data (budgets + policies) inserted.")

    async with AsyncSessionLocal() as session:
        # 预置用户（仅首次）
        for u in SEED_USERS:
            existing = await session.execute(
                User.__table__.select().where(User.username == u["username"])
            )
            if existing.first() is None:
                session.add(User(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    name=u["name"],
                    department=u["department"],
                    role=u["role"],
                ))
                print(f"  + user: {u['username']} ({u['role']})")
        await session.commit()
    print("Seed users inserted.")

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
