"""
=============================================================================
app/agent/knowledge/retriever.py — 知识检索器
=============================================================================
从向量知识库中检索与用户查询最相关的内容。

检索策略（混合）:
  1. 语义检索 — 基于向量相似度（ChromaDB）
  2. 关键词匹配 — 基于 TF-IDF 关键词权重（降级备用）
  3. 结构化检索 — 按文档类型过滤（如"费用标准"→只查 expense_policy.md）

返回格式: 排序后的相关文档片段列表，每段含相关度分数和来源。
=============================================================================
"""
from loguru import logger
from app.agent.knowledge.loader import get_chroma_client, is_available, _get_embedding_function


def semantic_search(query: str, top_k: int = 5, doc_type: str = "") -> list[dict]:
    """
    语义检索：基于向量相似度搜索知识库。
    自动适配 embedding 模型（text2vec-chinese / MiniLM / ChromaDB built-in）。
    """
    if not is_available():
        return []

    client = get_chroma_client()
    if not client:
        return []

    try:
        collection = client.get_collection("reimbursement_knowledge")
        where_filter = {"doc_type": doc_type} if doc_type else None

        # 判断是否需要用自定义 embedding 查询
        emb_fn = _get_embedding_function()
        if emb_fn and hasattr(emb_fn, "encode"):
            import numpy as np
            q_emb = emb_fn.encode([query], show_progress_bar=False)
            if isinstance(q_emb, np.ndarray):
                q_emb = q_emb.tolist()
            results = collection.query(
                query_embeddings=q_emb,
                n_results=top_k,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
        else:
            results = collection.query(
                query_texts=[query],
                n_results=top_k,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )

        if not results or not results["ids"] or not results["ids"][0]:
            return []

        docs = []
        for i in range(len(results["ids"][0])):
            content = results["documents"][0][i] if results["documents"] else ""
            metadata = results["metadatas"][0][i] if results["metadatas"] else {}
            distance = results["distances"][0][i] if results["distances"] else 1.0
            score = max(0, 1 - distance)

            docs.append({
                "content": content,
                "score": round(score, 4),
                "source": metadata.get("source", ""),
                "title": metadata.get("title", ""),
            })

        return docs

    except Exception as e:
        logger.warning(f"Semantic search failed: {e}")
        return []


def keyword_search(query: str, knowledge_texts: list[str]) -> list[dict]:
    """
    关键词匹配（降级备用）：当 ChromaDB 不可用时的简单检索方案。

    用 Jaccard 相似度（共现词/总词数）排序。
    """
    if not knowledge_texts:
        return []

    query_words = set(query.lower().split())
    if not query_words:
        return []

    results = []
    for text in knowledge_texts:
        text_words = set(text.lower().split())
        intersection = query_words & text_words
        if intersection:
            score = len(intersection) / len(query_words | text_words)
            results.append({
                "content": text[:500],
                "score": round(score, 4),
                "source": "keyword_match",
                "title": "",
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:3]


def retrieve(query: str, top_k: int = 5, doc_type: str = "") -> list[dict]:
    """
    统一检索入口：语义 → 关键词降级。

    Args:
        query    : 查询文本
        top_k    : 返回数量
        doc_type : 按类型过滤

    Returns:
        相关文档片段列表
    """
    # 先尝试语义检索
    results = semantic_search(query, top_k, doc_type)
    if results:
        logger.info(f"Retrieved {len(results)} chunks for '{query[:60]}' (semantic)")
        return results

    logger.info(f"Semantic search returned empty, using no knowledge context")
    return []


def build_context_for_llm(query: str, top_k: int = 3) -> str:
    """
    检索知识并格式化为 LLM 可用的上下文字符串。

    用于注入到提示词中，让 LLM 基于知识库回答。
    """
    docs = retrieve(query, top_k)
    if not docs:
        return ""

    lines = ["[引用知识库]"]
    for i, doc in enumerate(docs, 1):
        lines.append(
            f"\n--- 来源{i}: {doc['source']} ({doc['title']}) "
            f"(相关度: {doc['score']:.2%}) ---\n"
            f"{doc['content']}"
        )

    return "\n".join(lines)


def search_expense_policy(expense_type: str) -> str:
    """
    检索特定费用类型的政策。

    Args:
        expense_type: travel / entertainment / office / other

    Returns:
        相关政策文本
    """
    type_map = {
        "travel": "差旅",
        "entertainment": "招待",
        "office": "办公",
        "other": "其他",
    }
    keyword = type_map.get(expense_type, expense_type)

    # 优先用类型过滤 + 关键词检索
    results = semantic_search(f"{keyword} 费用标准 报销上限", top_k=3, doc_type="expense_policy")
    if results:
        return "\n\n".join(r["content"] for r in results)

    return ""
