"""
=============================================================================
app/agent/knowledge/loader.py — 知识库加载与向量索引构建
=============================================================================
将 data/knowledge/ 目录下的 Markdown 文档：
  1. 加载和解析
  2. 按段落分块（chunk）
  3. 通过嵌入模型向量化
  4. 存入 Chroma 向量数据库
  5. 提供检索入口

支持的文档:
  - expense_policy.md       费用标准政策
  - reimbursement_guide.md  报销流程指引
  - faq.md                  常见问题
  - department_info.md      部门架构信息

设计要点:
  - 懒加载：首次检索时才构建索引，避免启动时耗时
  - 增量更新：检测文件修改时间，过期自动重建
  - 降级策略：Chroma 不可用时返回空（不影响核心流程）
=============================================================================
"""
import os
import hashlib
from pathlib import Path
from loguru import logger

from app.core.config import get_settings

settings = get_settings()

# =============================================================================
# 路径配置
# =============================================================================
KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "knowledge"
CHROMA_DIR = Path(settings.CHROMA_PERSIST_DIR)

# =============================================================================
# 全局状态
# =============================================================================
_vectorstore = None
_doc_hashes: dict[str, str] = {}
_available = False


def _get_embedding_function():
    """
    获取嵌入函数。

    策略：优先使用本地轻量模型（all-MiniLM-L6-v2），不依赖外部 API。
    Python 3.12 兼容性：使用 sentence-transformers 的 CPU 版本。
    """
    try:
        from chromadb.utils import embedding_functions
        return embedding_functions.DefaultEmbeddingFunction()
    except Exception:
        try:
            from langchain_community.embeddings import HuggingFaceEmbeddings
            return HuggingFaceEmbeddings(
                model_name="all-MiniLM-L6-v2",
                model_kwargs={"device": "cpu"},
            )
        except ImportError:
            logger.warning("No embedding function available, using fallback")
            return None


def _load_documents() -> list[dict]:
    """
    加载所有知识库 Markdown 文档，按段落分块。

    分块策略:
      - 按 ## 二级标题切分（每个小节一个 chunk）
      - 每个 chunk 携带元数据（来源文件、标题、类型）
    """
    docs = []
    if not KNOWLEDGE_DIR.exists():
        logger.warning(f"Knowledge directory not found: {KNOWLEDGE_DIR}")
        return docs

    for md_file in sorted(KNOWLEDGE_DIR.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        file_hash = hashlib.md5(content.encode()).hexdigest()

        # 检查是否需要重新处理
        if _doc_hashes.get(md_file.name) == file_hash:
            continue
        _doc_hashes[md_file.name] = file_hash

        # 按 ## 标题分块
        sections = content.split("\n## ")
        for i, section in enumerate(sections):
            if not section.strip():
                continue

            # 第一个块可能没有 ## 开头（是标题行）
            if i == 0 and not section.startswith("##"):
                title = md_file.stem.replace("_", " ").title()
            else:
                lines = section.split("\n", 1)
                title = lines[0].strip() if lines else ""
                section = "## " + section

            docs.append({
                "content": section.strip(),
                "metadata": {
                    "source": md_file.name,
                    "title": title,
                    "doc_type": md_file.stem,
                },
            })

    logger.info(f"Loaded {len(docs)} knowledge chunks from {len(_doc_hashes)} files")
    return docs


def _build_index(docs: list[dict]) -> bool:
    """构建 Chroma 向量索引"""
    global _available

    if not docs:
        return False

    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        os.makedirs(CHROMA_DIR, exist_ok=True)

        client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        # 删除旧索引并重建
        try:
            client.delete_collection("reimbursement_knowledge")
        except Exception:
            pass

        collection = client.create_collection(
            name="reimbursement_knowledge",
            metadata={"description": "企业报销知识库"},
        )

        # 批量添加文档
        ids = [f"chunk_{i}" for i in range(len(docs))]
        contents = [d["content"] for d in docs]
        metadatas = [d["metadata"] for d in docs]

        batch_size = 50
        for i in range(0, len(docs), batch_size):
            end = min(i + batch_size, len(docs))
            collection.add(
                ids=ids[i:end],
                documents=contents[i:end],
                metadatas=metadatas[i:end],
            )

        _available = True
        logger.info(f"Knowledge index built: {len(docs)} chunks in ChromaDB")
        return True

    except ImportError:
        logger.warning("chromadb not installed, knowledge base disabled")
        return False
    except Exception as e:
        logger.error(f"Failed to build knowledge index: {e}")
        return False


def get_or_build_index() -> bool:
    """获取或构建知识库索引（懒加载）"""
    docs = _load_documents()
    if docs:
        return _build_index(docs)
    return False


def is_available() -> bool:
    """知识库是否可用"""
    return _available


def get_chroma_client():
    """获取 Chroma 客户端（用于检索）"""
    if not _available:
        return None
    try:
        import chromadb
        return chromadb.PersistentClient(path=str(CHROMA_DIR))
    except Exception:
        return None
