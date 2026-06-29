import asyncio

async def seed():
    from sqlalchemy import text
    from app.core.database import AsyncSessionLocal
    from app.models.reimbursement import DepartmentBudget

    async with AsyncSessionLocal() as session:
        result = await session.execute(text("SELECT COUNT(*) FROM department_budget"))
        count = result.scalar()
        if count > 0:
            print(f"数据库已有 {count} 条部门预算记录，跳过种子数据导入。")
            return

        budgets = [
            DepartmentBudget(department="技术部", annual_budget=500000, used_amount=200000, fiscal_year=2026),
            DepartmentBudget(department="市场部", annual_budget=300000, used_amount=250000, fiscal_year=2026),
            DepartmentBudget(department="财务部", annual_budget=200000, used_amount=50000, fiscal_year=2026),
            DepartmentBudget(department="人事部", annual_budget=150000, used_amount=80000, fiscal_year=2026),
            DepartmentBudget(department="研发部", annual_budget=800000, used_amount=400000, fiscal_year=2026),
            DepartmentBudget(department="运营部", annual_budget=250000, used_amount=100000, fiscal_year=2026),
        ]
        session.add_all(budgets)
        await session.commit()
        print(f"已导入 {len(budgets)} 条部门预算模拟数据。")


if __name__ == "__main__":
    asyncio.run(seed())
