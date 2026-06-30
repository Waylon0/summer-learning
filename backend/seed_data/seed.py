"""
=============================================================================
seed_data/seed.py — 种子数据初始化脚本
=============================================================================
用于首次部署时向数据库导入初始数据（部门预算）。

使用方式：
  cd backend
  uv run python seed_data/seed.py

运行效果：
  如果 department_budget 表为空 → 插入 6 个部门的模拟预算数据
  如果已有数据 → 跳过（避免重复导入）
=============================================================================
"""
import asyncio


async def seed():
    """主函数：检查并导入种子数据"""
    from sqlalchemy import text                            # 直接写 SQL（用于简单的 COUNT 查询）
    from app.core.database import AsyncSessionLocal        # 数据库会话工厂
    from app.models.reimbursement import DepartmentBudget   # 部门预算 ORM 模型

    async with AsyncSessionLocal() as session:
        # --- 检查是否已有数据 ---
        result = await session.execute(
            text("SELECT COUNT(*) FROM department_budget")
        )
        count = result.scalar()                            # 获取计数结果
        if count > 0:
            print(f"数据库已有 {count} 条部门预算记录，跳过种子数据导入。")
            return

        # --- 创建 6 个部门的预算数据 ---
        budgets = [
            DepartmentBudget(department="技术部",  annual_budget=500000, used_amount=200000, fiscal_year=2026),
            DepartmentBudget(department="市场部",  annual_budget=300000, used_amount=250000, fiscal_year=2026),
            DepartmentBudget(department="财务部",  annual_budget=200000, used_amount=50000,  fiscal_year=2026),
            DepartmentBudget(department="人事部",  annual_budget=150000, used_amount=80000,  fiscal_year=2026),
            DepartmentBudget(department="研发部",  annual_budget=800000, used_amount=400000, fiscal_year=2026),
            DepartmentBudget(department="运营部",  annual_budget=250000, used_amount=100000, fiscal_year=2026),
        ]
        # add_all 一次性添加所有对象（比逐个 add 效率高）
        session.add_all(budgets)
        await session.commit()
        print(f"已导入 {len(budgets)} 条部门预算模拟数据。")


if __name__ == "__main__":
    asyncio.run(seed())
