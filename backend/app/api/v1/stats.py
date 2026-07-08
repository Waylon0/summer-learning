"""
=============================================================================
app/api/v1/stats.py — 费用统计 API
=============================================================================
对应 docs/BACKEND-API-NEEDS.md：
  P0  GET /stats/trend              近 N 个月费用趋势（折线图）
  P0  GET /stats/personal           个人报销统计
  P0  GET /stats/department-ranking 部门费用排行
  P2  GET /stats/summary            Dashboard 汇总卡片

权限：需登录。个人统计默认查询当前用户，普通员工不可查看他人。
=============================================================================
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.models.user import User
from app.services.stats_svc import StatsService
from app.schemas.stats import (
    TrendResponse,
    PersonalStatsResponse,
    DepartmentRankingResponse,
    SummaryResponse,
)

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/trend", response_model=TrendResponse)
async def get_trend(
    months: int = Query(6, ge=1, le=24, description="近几个月"),
    department: str | None = Query(None, description="可选，按部门筛选"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """近 N 个月费用趋势，按费用类型分色"""
    if user.role == "employee":
        department = user.department
    elif user.role == "manager":
        if department and department != user.department:
            raise HTTPException(status_code=403, detail=f"只能查看{user.department}的统计")
        department = user.department
    return await StatsService(db).trend(months=months, department=department)


@router.get("/personal", response_model=PersonalStatsResponse)
async def get_personal_stats(
    user_id: str | None = Query(None, description="用户ID，默认当前登录用户"),
    month: str | None = Query(None, description="YYYY-MM，默认当前月"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """个人报销统计（本月 / 上月 / 状态分布）"""
    target_id = user_id or user.id
    if user.role == "employee" and target_id != user.id:
        raise HTTPException(status_code=403, detail="只能查看本人的统计")
    return await StatsService(db).personal(user_id=target_id, month=month)


@router.get("/department-ranking", response_model=DepartmentRankingResponse)
async def get_department_ranking(
    period: str = Query("year", description="month / quarter / year"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """部门费用排行"""
    return await StatsService(db).department_ranking(period=period)


@router.get("/summary", response_model=SummaryResponse)
async def get_summary(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Dashboard 顶部汇总卡片"""
    return await StatsService(db).summary()
