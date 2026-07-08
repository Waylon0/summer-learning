"""
=============================================================================
app/agent/knowledge/loader.py — 知识库加载与向量索引构建
=============================================================================
将 data/knowledge/ 目录下的 Markdown 文档向量化存入 ChromaDB。

嵌入模型:
  优先 — shibing624/text2vec-base-chinese (中文语义, 384维, ~400MB)
  降级 — all-MiniLM-L6-v2 (英文, ChromaDB 内置)
=============================================================================
"""
import os
import hashlib
from pathlib import Path
from loguru import logger

from app.core.config import get_settings

settings = get_settings()

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data" / "knowledge"
CHROMA_DIR = Path(settings.CHROMA_PERSIST_DIR)

_vectorstore = None
_doc_hashes: dict[str, str] = {}
_available = False
_embedding_fn = None


def _get_embedding_function():
    """
    获取中文嵌入函数。

    策略:
      1. sentence-transformers + text2vec-base-chinese (推荐, 中文最佳)
      2. sentence-transformers + all-MiniLM-L6-v2 (英文降级)
      3. ChromaDB 内置 DefaultEmbeddingFunction (自动下载)
    """
    global _embedding_fn
    if _embedding_fn is not None:
        return _embedding_fn

    # Strategy 1: Chinese model via sentence-transformers
    try:
        from sentence_transformers import SentenceTransformer
        _embedding_fn = SentenceTransformer(
            "shibing624/text2vec-base-chinese",
            device="cpu",
        )
        logger.info("Embedding: shibing624/text2vec-base-chinese (Chinese, 384d)")
        return _embedding_fn
    except Exception as e:
        logger.info(f"text2vec not available: {e}")

    # Strategy 2: English model via sentence-transformers
    try:
        from sentence_transformers import SentenceTransformer
        _embedding_fn = SentenceTransformer(
            "sentence-transformers/all-MiniLM-L6-v2",
            device="cpu",
        )
        logger.warning("Embedding: all-MiniLM-L6-v2 (English — Chinese queries may be less accurate)")
        return _embedding_fn
    except Exception as e:
        logger.info(f"MiniLM not available: {e}")

    # Strategy 3: ChromaDB built-in
    try:
        from chromadb.utils import embedding_functions
        _embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        logger.warning("Embedding: ChromaDB Default (all-MiniLM-L6-v2)")
        return _embedding_fn
    except Exception:
        logger.warning("No embedding function available")
        return None


def _embed_texts(texts: list[str]) -> list[list[float]]:
    """将文本列表转为向量"""
    fn = _get_embedding_function()
    if fn is None:
        return [[0.0] * 384 for _ in texts]

    # sentence-transformers: encode() returns numpy array
    if hasattr(fn, "encode"):
        import numpy as np
        embeddings = fn.encode(texts, show_progress_bar=False)
        if isinstance(embeddings, np.ndarray):
            return embeddings.tolist()
        return [e.tolist() if hasattr(e, "tolist") else e for e in embeddings]

    # ChromaDB embedding function: __call__
    if callable(fn):
        result = fn(texts)
        if isinstance(result, list):
            return result
        return [result]

    return [[0.0] * 384 for _ in texts]


def _load_documents() -> list[dict]:
    """加载所有知识库 Markdown 文档，按段落分块"""
    docs = []
    if not KNOWLEDGE_DIR.exists():
        logger.warning(f"Knowledge directory not found: {KNOWLEDGE_DIR}")
        return docs

    for md_file in sorted(KNOWLEDGE_DIR.glob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        file_hash = hashlib.md5(content.encode()).hexdigest()

        if _doc_hashes.get(md_file.name) == file_hash:
            continue
        _doc_hashes[md_file.name] = file_hash

        sections = content.split("\n## ")
        for i, section in enumerate(sections):
            if not section.strip():
                continue
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

        collection = None
        try:
            collection = client.get_collection("reimbursement_knowledge")
        except Exception:
            pass

        if collection is None:
            emb_fn = _get_embedding_function()
            if emb_fn and hasattr(emb_fn, "encode"):
                # sentence-transformers model: pre-compute embeddings
                collection = client.create_collection(
                    name="reimbursement_knowledge",
                    metadata={"description": "企业报销知识库 (text2vec-chinese)"},
                )
            else:
                # ChromaDB built-in: let it handle embedding internally
                collection = client.create_collection(
                    name="reimbursement_knowledge",
                    metadata={"description": "企业报销知识库 (ChromaDB default)"},
                    embedding_function=emb_fn if emb_fn else None,
                )

        ids = [f"chunk_{i}" for i in range(len(docs))]
        contents = [d["content"] for d in docs]
        metadatas = [d["metadata"] for d in docs]

        if _get_embedding_function() and hasattr(_get_embedding_function(), "encode"):
            # Pre-compute embeddings for sentence-transformers models
            embeddings = _embed_texts(contents)
            batch_size = 50
            for i in range(0, len(docs), batch_size):
                end = min(i + batch_size, len(docs))
                try:
                    collection.upsert(
                        ids=ids[i:end],
                        embeddings=embeddings[i:end],
                        documents=contents[i:end],
                        metadatas=metadatas[i:end],
                    )
                except Exception:
                    collection.upsert(
                        ids=ids[i:end],
                        documents=contents[i:end],
                        metadatas=metadatas[i:end],
                    )
        else:
            # Let ChromaDB handle embedding internally (uses built-in EF)
            batch_size = 50
            for i in range(0, len(docs), batch_size):
                end = min(i + batch_size, len(docs))
                try:
                    collection.upsert(
                        ids=ids[i:end],
                        documents=contents[i:end],
                        metadatas=metadatas[i:end],
                    )
                except Exception:
                    collection.add(
                        ids=ids[i:end],
                        documents=contents[i:end],
                        metadatas=metadatas[i:end],
                    )

        _available = True
        logger.info(f"Knowledge index built: {len(docs)} chunks in ChromaDB")
        return True

    except ImportError:
        logger.warning("chromadb not installed — run: uv sync")
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


def rebuild_index() -> bool:
    """强制重建知识库索引"""
    global _available, _doc_hashes, _embedding_fn
    _doc_hashes.clear()
    _available = False
    _embedding_fn = None
    docs = _load_documents()
    if not docs:
        logger.warning("No knowledge documents found to index")
        return False
    return _build_index(docs)


def is_available() -> bool:
    return _available


def get_chroma_client():
    if not _available:
        return None
    try:
        import chromadb
        return chromadb.PersistentClient(path=str(CHROMA_DIR))
    except Exception:
        return None
