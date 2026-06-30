"""
=============================================================================
app/api/v1/reimbursements.py — 报销单 CRUD API
=============================================================================
提供报销单的增删改查 REST 接口：

  POST   /api/v1/reimbursements         — 创建报销单
  GET    /api/v1/reimbursements/{id}    — 查询单个报销单
  GET    /api/v1/reimbursements         — 列表查询（支持筛选）
=============================================================================
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db                       # 数据库会话依赖注入
from app.services.reimbursement_svc import ReimbursementService  # 业务逻辑层
from app.schemas.reimbursement import ReimbursementCreate, ReimbursementResponse

router = APIRouter(prefix="/reimbursements", tags=["reimbursements"])


# =============================================================================
# POST /reimbursements —— 创建报销单
# =============================================================================
@router.post("", response_model=ReimbursementResponse)
async def create_reimbursement(
    data: ReimbursementCreate,                             # FastAPI 自动校验请求体
    db: AsyncSession = Depends(get_db),                    # FastAPI 自动注入数据库会话
):
    """
    创建一条新的报销申请。

    步骤：Service.create() → 写数据库 → 刷新 → 返回给前端
    """
    svc = ReimbursementService(db)
    reimb = await svc.create(data, data.invoices)
    # refresh 重新从数据库加载关联的 invoices 和 approvals（包含数据库生成的值）
    await db.refresh(reimb, ["invoices", "approvals"])
    return _to_response(reimb)


# =============================================================================
# GET /reimbursements/{reimb_id} —— 查询单个报销单
# =============================================================================
@router.get("/{reimb_id}", response_model=ReimbursementResponse)
async def get_reimbursement(reimb_id: str, db: AsyncSession = Depends(get_db)):
    """根据报销单 ID 查询详情"""
    svc = ReimbursementService(db)
    reimb = await svc.get_by_id(reimb_id)
    if not reimb:
        raise HTTPException(status_code=404, detail="报销单不存在")
    return _to_response(reimb)


# =============================================================================
# GET /reimbursements —— 列表查询
# =============================================================================
@router.get("", response_model=list[ReimbursementResponse])
async def list_reimbursements(
    user_id: str = None,        # 可选：按用户筛选
    status: str = None,          # 可选：按状态筛选
    limit: int = 50,             # 最多返回 50 条（防止一次查太多）
    db: AsyncSession = Depends(get_db),
):
    """查询报销单列表，支持按用户和状态筛选"""
    svc = ReimbursementService(db)
    if user_id:
        reimbs = await svc.list_by_user(user_id, limit)
    else:
        reimbs = await svc.list_by_status(status, limit=limit)
    return [_to_response(r) for r in reimbs]


# =============================================================================
# 辅助函数：ORM 对象 → Pydantic 响应
# =============================================================================
def _to_response(reimb) -> ReimbursementResponse:
    """
    把 SQLAlchemy ORM 对象转换成 Pydantic 响应模型。

    为什么要转换？
      ORM 对象是数据库行的映射，不能直接 JSON 序列化。
      Pydantic 模型是专门为 API 响应设计的，FastAPI 能自动序列化。
    """
    return ReimbursementResponse(
        id=reimb.id,
        user_id=reimb.user_id,
        user_name=reimb.user_name,
        department=reimb.department,
        expense_type=reimb.expense_type,
        total_amount=float(reimb.total_amount),
        description=reimb.description,
        invoice_count=reimb.invoice_count,
        need_special_approval=reimb.need_special_approval,
        budget_remaining_after=float(reimb.budget_remaining_after) if reimb.budget_remaining_after else None,
        status=reimb.status,
        created_at=reimb.created_at.isoformat() if reimb.created_at else None,
        updated_at=reimb.updated_at.isoformat() if reimb.updated_at else None,
        invoices=[i.to_dict() for i in (reimb.invoices or [])],
        approvals=[a.to_dict() for a in (reimb.approvals or [])],
    )
