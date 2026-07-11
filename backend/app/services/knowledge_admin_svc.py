"""
=============================================================================
app/services/knowledge_admin_svc.py — 知识库【在线管理】业务服务（阶段二·方案 A）
=============================================================================
以 data/knowledge/*.md 文件为唯一真源，提供在线维护 RAG 政策知识库的能力，
消除“改政策要登服务器改文件 + 跑 CLI”的滞后性。不修改 loader/retriever 内部逻辑：

  1. list_docs      — 列出知识文档（含启用/停用状态、大小、更新时间）
  2. read_doc       — 读取某文档原文
  3. save_doc       — 新建/覆盖保存文档（默认保存后重建索引）
  4. disable_doc    — 停用（软删）：{key}.md → {key}.md.disabled（glob("*.md") 天然排除）
  5. enable_doc     — 启用：{key}.md.disabled → {key}.md
  6. reindex        — 手动同步重建向量索引（复用 loader.rebuild_index）
  7. status         — 索引状态（是否可用、后端、分块数、各文件 MD5）
  8. search         — 调试检索（复用 retriever）

安全：doc_key 走白名单（app/services/knowledge_rules），杜绝路径遍历；所有落盘路径都
再次校验其父目录必须是 KNOWLEDGE_DIR。审计写入 knowledge_audit 表。

重建“尽力而为”：失败不影响文件已保存，返回 reindexed=False + reason，可稍后手动 /reindex。
每次改动都会清理 loader 的 _doc_hashes 与 retriever 的关键词降级缓存，避免读到旧内容。
=============================================================================
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.models.reimbursement import KnowledgeAudit
from app.services import knowledge_rules as kr
from app.core.exceptions import BusinessException, NotFoundException


class KnowledgeNotFoundError(NotFoundException):
    """知识文档不存在。"""
    def __init__(self, doc_key: str):
        super().__init__(resource="知识文档", identifier=doc_key)


def _knowledge_dir() -> Path:
    """知识库目录（复用 loader 的常量，保证与索引读取同一目录）。"""
    from app.agent.knowledge.loader import KNOWLEDGE_DIR
    return Path(KNOWLEDGE_DIR)


def _assert_within_dir(path: Path, base: Path) -> None:
    """确保目标路径落在知识库目录内（纵深防御，杜绝路径遍历）。"""
    try:
        path.resolve().relative_to(base.resolve())
    except (ValueError, RuntimeError):
        raise BusinessException("非法的文档路径。", error_code="INVALID_DOC_PATH")


def _invalidate_caches() -> None:
    """清理与文件内容相关的进程内缓存，确保下次检索/重建读到最新文件。"""
    try:
        from app.agent.knowledge import loader
        loader._doc_hashes.clear()
    except Exception as e:
        logger.warning(f"清理 loader._doc_hashes 失败（不阻断）: {e}")
    try:
        from app.agent.knowledge import retriever
        retriever._KB_TEXT_CACHE = None
    except Exception as e:
        logger.warning(f"清理 retriever._KB_TEXT_CACHE 失败（不阻断）: {e}")


def _first_title(content: str, fallback: str) -> str:
    """从 Markdown 取首个标题（# 或 ##）作为展示名，取不到用 fallback。"""
    for line in (content or "").splitlines():
        s = line.strip()
        if s.startswith("#"):
            t = s.lstrip("#").strip()
            if t:
                return t
    return fallback


class KnowledgeAdminService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.dir = _knowledge_dir()

    # ------------------------------------------------------------ 审计
    async def _audit(self, doc_key: str, action: str, operator: str,
                     reason: str | None, reindexed: bool) -> KnowledgeAudit:
        rec = KnowledgeAudit(
            doc_key=doc_key, action=action, operator=operator or "",
            reason=reason or None, reindexed=bool(reindexed),
        )
        self.db.add(rec)
        await self.db.commit()
        await self.db.refresh(rec)
        return rec

    # ------------------------------------------------------------ 路径解析
    def _enabled_path(self, doc_key: str) -> Path:
        p = self.dir / kr.enabled_filename(doc_key)
        _assert_within_dir(p, self.dir)
        return p

    def _disabled_path(self, doc_key: str) -> Path:
        p = self.dir / kr.disabled_filename(doc_key)
        _assert_within_dir(p, self.dir)
        return p

    def _require_valid_key(self, doc_key: str) -> None:
        if not kr.is_valid_doc_key(doc_key):
            raise BusinessException(
                "doc_key 仅允许字母/数字/下划线（1~64 位），不得包含路径分隔符或点号。",
                error_code="INVALID_DOC_KEY",
            )

    # ------------------------------------------------------------ 1. 列表
    def list_docs(self) -> list[dict]:
        """列出知识库目录下所有文档（启用 .md 与 停用 .md.disabled）。"""
        docs: list[dict] = []
        if not self.dir.exists():
            return docs
        seen: dict[str, dict] = {}
        for f in sorted(self.dir.iterdir()):
            if not f.is_file():
                continue
            key = kr.doc_key_from_filename(f.name)
            if not key:
                continue
            disabled = kr.is_disabled_filename(f.name)
            content = ""
            try:
                content = f.read_text(encoding="utf-8")
            except Exception:
                pass
            info = {
                "doc_key": key,
                "title": _first_title(content, key),
                "active": not disabled,
                "bytes": f.stat().st_size,
                "chunks": self._count_chunks(content),
                "updated_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            }
            # 若同一 key 同时存在 .md 与 .md.disabled（异常），以启用态为准
            if key not in seen or info["active"]:
                seen[key] = info
        return list(seen.values())

    @staticmethod
    def _count_chunks(content: str) -> int:
        """按 loader 相同规则（'\\n## ' 切分）估算分块数。"""
        if not content or not content.strip():
            return 0
        sections = content.split("\n## ")
        return len([s for s in sections if s.strip()])

    # ------------------------------------------------------------ 2. 读取
    def read_doc(self, doc_key: str) -> dict:
        self._require_valid_key(doc_key)
        enabled = self._enabled_path(doc_key)
        disabled = self._disabled_path(doc_key)
        if enabled.exists():
            path, active = enabled, True
        elif disabled.exists():
            path, active = disabled, False
        else:
            raise KnowledgeNotFoundError(doc_key)
        content = path.read_text(encoding="utf-8")
        return {
            "doc_key": doc_key,
            "title": _first_title(content, doc_key),
            "active": active,
            "content": content,
            "bytes": path.stat().st_size,
            "chunks": self._count_chunks(content),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        }

    # ------------------------------------------------------------ 3. 保存/新建
    async def save_doc(
        self, doc_key: str, content: str, operator: str,
        reason: str | None = None, reindex: bool = True,
        create: bool = False,
    ) -> dict:
        """新建(create=True)或覆盖保存文档。写盘 → 审计 →（默认）重建。"""
        self._require_valid_key(doc_key)
        if not content or not content.strip():
            raise BusinessException("文档内容不能为空。", error_code="EMPTY_CONTENT")

        enabled = self._enabled_path(doc_key)
        disabled = self._disabled_path(doc_key)
        exists = enabled.exists() or disabled.exists()
        if create and exists:
            raise BusinessException(
                f"文档「{doc_key}」已存在，请改用保存/编辑。", error_code="DOC_ALREADY_EXISTS"
            )
        if not create and not exists:
            # 允许 PUT 直接创建？按设计 PUT 为保存/覆盖，不存在则视为新建落盘
            pass

        # 若当前是停用态，编辑落到停用文件（保持停用状态），否则落到启用文件
        target = disabled if (disabled.exists() and not enabled.exists()) else enabled
        self.dir.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _invalidate_caches()

        action = "create" if (create or not exists) else "update"
        reindexed, reason_idx = self._maybe_reindex(reindex)
        await self._audit(doc_key, action, operator, reason, reindexed)
        logger.info(f"知识文档保存: {doc_key} action={action} bytes={target.stat().st_size} reindexed={reindexed} by {operator}")

        content_now = target.read_text(encoding="utf-8")
        return {
            "doc_key": doc_key,
            "action": action,
            "active": target == enabled,
            "bytes": target.stat().st_size,
            "chunks": self._count_chunks(content_now),
            "reindexed": reindexed,
            "reindex_message": reason_idx,
            "index_chunks_total": self._index_total(),
        }

    # ------------------------------------------------------------ 4. 停用（软删）
    async def disable_doc(self, doc_key: str, operator: str,
                          reason: str | None = None, reindex: bool = True) -> dict:
        self._require_valid_key(doc_key)
        enabled = self._enabled_path(doc_key)
        disabled = self._disabled_path(doc_key)
        if not enabled.exists():
            if disabled.exists():
                raise BusinessException(f"文档「{doc_key}」已处于停用状态。", error_code="ALREADY_DISABLED")
            raise KnowledgeNotFoundError(doc_key)
        enabled.rename(disabled)
        _invalidate_caches()
        reindexed, reason_idx = self._maybe_reindex(reindex)
        await self._audit(doc_key, "disable", operator, reason, reindexed)
        logger.info(f"知识文档停用(软删): {doc_key} reindexed={reindexed} by {operator}")
        return {"doc_key": doc_key, "active": False, "reindexed": reindexed,
                "reindex_message": reason_idx, "index_chunks_total": self._index_total()}

    # ------------------------------------------------------------ 5. 启用
    async def enable_doc(self, doc_key: str, operator: str,
                         reason: str | None = None, reindex: bool = True) -> dict:
        self._require_valid_key(doc_key)
        enabled = self._enabled_path(doc_key)
        disabled = self._disabled_path(doc_key)
        if not disabled.exists():
            if enabled.exists():
                raise BusinessException(f"文档「{doc_key}」已处于启用状态。", error_code="ALREADY_ENABLED")
            raise KnowledgeNotFoundError(doc_key)
        disabled.rename(enabled)
        _invalidate_caches()
        reindexed, reason_idx = self._maybe_reindex(reindex)
        await self._audit(doc_key, "enable", operator, reason, reindexed)
        logger.info(f"知识文档启用: {doc_key} reindexed={reindexed} by {operator}")
        return {"doc_key": doc_key, "active": True, "reindexed": reindexed,
                "reindex_message": reason_idx, "index_chunks_total": self._index_total()}

    # ------------------------------------------------------------ 6. 手动重建
    async def reindex(self, operator: str, reason: str | None = None) -> dict:
        _invalidate_caches()
        reindexed, msg = self._maybe_reindex(True)
        await self._audit("*", "reindex", operator, reason, reindexed)
        logger.info(f"知识库手动重建: reindexed={reindexed} by {operator}")
        return {"reindexed": reindexed, "reindex_message": msg,
                "index_chunks_total": self._index_total()}

    # ------------------------------------------------------------ 7. 状态
    def status(self) -> dict:
        from app.agent.knowledge import loader
        docs = self.list_docs()
        return {
            "index_available": bool(loader.is_available()),
            "embedding_backend": loader.embedding_backend_name(),
            "index_chunks_total": self._index_total(),
            "doc_count": len(docs),
            "active_count": sum(1 for d in docs if d["active"]),
            "docs": [
                {"doc_key": d["doc_key"], "active": d["active"],
                 "chunks": d["chunks"], "md5": self._doc_md5(d["doc_key"])}
                for d in docs
            ],
        }

    # ------------------------------------------------------------ 8. 检索调试
    def search(self, query: str, top_k: int = 3) -> list[dict]:
        from app.agent.knowledge.retriever import retrieve
        if not query or not query.strip():
            raise BusinessException("检索关键词不能为空。", error_code="EMPTY_QUERY")
        return retrieve(query, top_k=max(1, min(top_k, 10)))

    # ------------------------------------------------------------ 内部：重建/统计
    def _maybe_reindex(self, do: bool) -> tuple[bool, str]:
        """按需同步重建索引。返回 (是否成功重建, 说明)。尽力而为，失败不抛。"""
        if not do:
            return False, "未触发重建（reindex=false），可稍后手动 POST /knowledge/reindex。"
        try:
            from app.agent.knowledge.loader import rebuild_index
            ok = rebuild_index()
            if ok:
                return True, "索引已重建。"
            return False, "重建未成功（知识库为空或向量库不可用），已保留文件改动，可稍后重试。"
        except Exception as e:
            logger.warning(f"知识库重建失败（不阻断）: {e}")
            return False, f"重建异常：{e}（文件已保存，可稍后重试）。"

    def _index_total(self) -> int:
        try:
            from app.agent.knowledge.loader import collection_chunk_count
            return collection_chunk_count()
        except Exception:
            return 0

    def _doc_md5(self, doc_key: str) -> str:
        for p in (self._enabled_path(doc_key), self._disabled_path(doc_key)):
            if p.exists():
                try:
                    return hashlib.md5(p.read_bytes()).hexdigest()
                except Exception:
                    return ""
        return ""
