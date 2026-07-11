"""
=============================================================================
app/api/v1/knowledge.py — 知识库管理 API（知识库管理模块 · 阶段二·方案 A）
=============================================================================
在线维护 RAG 政策知识库（data/knowledge/*.md），保存后可自动重建向量索引，
消除“改政策要登服务器改文件 + 跑 CLI”的滞后性。

  GET    /knowledge/docs                      列出文档（含启用/停用状态）
  GET    /knowledge/docs/{doc_key}            读取文档原文
  PUT    /knowledge/docs/{doc_key}            保存/覆盖文档（默认保存后重建）
  POST   /knowledge/docs                      新建文档（默认重建）
  POST   /knowledge/docs/{doc_key}/disable    停用（软删）
  POST   /knowledge/docs/{doc_key}/enable     启用
  POST   /knowledge/reindex                   手动同步重建索引
  GET    /knowledge/status                    索引状态
  POST   /knowledge/search                    检索调试

权限（已敲定）：编辑/停用/启用/重建 仅 admin；读取/状态/检索 admin+finance。
业务异常由全局异常处理器统一转 HTTP。
=============================================================================
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.core.database import get_db
from app.core.deps import require_role
from app.models.user import User
from app.services.knowledge_admin_svc import KnowledgeAdminService
from app.schemas.knowledge import (
    KnowledgeSaveRequest, KnowledgeCreateRequest, KnowledgeToggleRequest,
    KnowledgeReindexRequest, KnowledgeSearchRequest,
    KnowledgeDocSummary, KnowledgeDocDetail,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

# 编辑类：仅 admin；读取/调试类：admin + finance
_editor = require_role("admin")
_reader = require_role("admin", "finance")


# =============================================================================
# 列表 / 读取（admin + finance）
# =============================================================================
@router.get("/docs", response_model=list[KnowledgeDocSummary])
async def list_docs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_reader),
):
    """列出知识库全部文档（含启用 .md 与停用 .md.disabled）。"""
    svc = KnowledgeAdminService(db)
    return [KnowledgeDocSummary(**d) for d in svc.list_docs()]


@router.get("/docs/{doc_key}", response_model=KnowledgeDocDetail)
async def read_doc(
    doc_key: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_reader),
):
    """读取某知识文档原文（Markdown）。"""
    svc = KnowledgeAdminService(db)
    return KnowledgeDocDetail(**svc.read_doc(doc_key))


# =============================================================================
# 保存 / 新建（仅 admin）
# =============================================================================
@router.put("/docs/{doc_key}")
async def save_doc(
    doc_key: str,
    data: KnowledgeSaveRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_editor),
):
    """保存/覆盖文档正文（仅 admin）。reindex 默认 true（保存即重建）。"""
    svc = KnowledgeAdminService(db)
    result = await svc.save_doc(
        doc_key=doc_key, content=data.content, operator=user.name,
        reason=data.reason, reindex=data.reindex, create=False,
    )
    logger.info(f"[API] 保存知识文档 {doc_key} by {user.username}")
    return result


@router.post("/docs", status_code=201)
async def create_doc(
    data: KnowledgeCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_editor),
):
    """新建知识文档（仅 admin）。doc_key 已存在则 400。"""
    svc = KnowledgeAdminService(db)
    result = await svc.save_doc(
        doc_key=data.doc_key, content=data.content, operator=user.name,
        reason=data.reason, reindex=data.reindex, create=True,
    )
    logger.info(f"[API] 新建知识文档 {data.doc_key} by {user.username}")
    return result


# =============================================================================
# 停用（软删）/ 启用（仅 admin）
# =============================================================================
@router.post("/docs/{doc_key}/disable")
async def disable_doc(
    doc_key: str,
    data: KnowledgeToggleRequest = KnowledgeToggleRequest(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_editor),
):
    """停用（软删）知识文档（仅 admin）：移出检索，文件保留可恢复。"""
    svc = KnowledgeAdminService(db)
    result = await svc.disable_doc(doc_key, operator=user.name, reason=data.reason, reindex=data.reindex)
    logger.info(f"[API] 停用知识文档 {doc_key} by {user.username}")
    return result


@router.post("/docs/{doc_key}/enable")
async def enable_doc(
    doc_key: str,
    data: KnowledgeToggleRequest = KnowledgeToggleRequest(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_editor),
):
    """启用知识文档（仅 admin）：重新纳入检索。"""
    svc = KnowledgeAdminService(db)
    result = await svc.enable_doc(doc_key, operator=user.name, reason=data.reason, reindex=data.reindex)
    logger.info(f"[API] 启用知识文档 {doc_key} by {user.username}")
    return result


# =============================================================================
# 手动重建 / 状态 / 检索调试
# =============================================================================
@router.post("/reindex")
async def reindex(
    data: KnowledgeReindexRequest = KnowledgeReindexRequest(),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_editor),
):
    """手动同步重建知识库向量索引（仅 admin）。"""
    svc = KnowledgeAdminService(db)
    result = await svc.reindex(operator=user.name, reason=data.reason)
    logger.info(f"[API] 手动重建知识库 by {user.username} reindexed={result.get('reindexed')}")
    return result


@router.get("/status")
async def status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_reader),
):
    """知识库索引状态：可用性、embedding 后端、分块数、各文件 MD5。"""
    svc = KnowledgeAdminService(db)
    return svc.status()


@router.post("/search")
async def search(
    data: KnowledgeSearchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(_reader),
):
    """（调试）对知识库做一次检索，返回命中片段与相关度，验证更新效果。"""
    svc = KnowledgeAdminService(db)
    hits = svc.search(data.query, top_k=data.top_k)
    return {"query": data.query, "count": len(hits), "hits": hits}
