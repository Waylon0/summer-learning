"""
=============================================================================
app/schemas/knowledge.py — 知识库管理 数据校验模型（阶段二·方案 A）
=============================================================================
RAG 政策知识库在线维护接口的请求/响应模型。写操作仅 admin，读放开 finance。
=============================================================================
"""
from pydantic import BaseModel, Field
from typing import Optional


# ----------------------------------------------------------------- 请求
class KnowledgeSaveRequest(BaseModel):
    """保存/覆盖文档正文（PUT /knowledge/docs/{doc_key}）。"""
    content: str = Field(..., min_length=1, description="Markdown 正文（非空）")
    reason: Optional[str] = Field(None, description="变更原因（审计留痕，可空）")
    reindex: bool = Field(True, description="是否保存后立即重建索引（默认 true）")


class KnowledgeCreateRequest(BaseModel):
    """新建文档（POST /knowledge/docs）。"""
    doc_key: str = Field(..., description="文档标识（字母/数字/下划线，1~64 位）")
    content: str = Field(..., min_length=1, description="Markdown 正文（非空）")
    reason: Optional[str] = Field(None, description="变更原因（可空）")
    reindex: bool = Field(True, description="是否保存后立即重建索引（默认 true）")


class KnowledgeToggleRequest(BaseModel):
    """停用/启用（POST /knowledge/docs/{doc_key}/disable|enable）。"""
    reason: Optional[str] = Field(None, description="变更原因（可空）")
    reindex: bool = Field(True, description="是否操作后立即重建索引（默认 true）")


class KnowledgeReindexRequest(BaseModel):
    """手动重建（POST /knowledge/reindex）。"""
    reason: Optional[str] = Field(None, description="重建原因（可空）")


class KnowledgeSearchRequest(BaseModel):
    """检索调试（POST /knowledge/search）。"""
    query: str = Field(..., min_length=1, description="检索关键词")
    top_k: int = Field(3, ge=1, le=10, description="返回条数（1~10）")


# ----------------------------------------------------------------- 响应
class KnowledgeDocSummary(BaseModel):
    """文档列表项。"""
    doc_key: str
    title: str
    active: bool
    bytes: int
    chunks: int
    updated_at: Optional[str] = None


class KnowledgeDocDetail(BaseModel):
    """文档详情（含正文）。"""
    doc_key: str
    title: str
    active: bool
    content: str
    bytes: int
    chunks: int
    updated_at: Optional[str] = None
