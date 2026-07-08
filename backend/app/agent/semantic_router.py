"""
=============================================================================
app/agent/semantic_router.py — 语义向量意图路由（NLP 层，离线兜底）
=============================================================================
用「例句相似度」代替死板关键词：把用户输入向量化，与注册表里各意图的
典型例句比对，取最相似者。抗自然语言表达变化（换词/语序/口语化）。

可插拔 embedding 后端（由 config.EMBEDDING_BACKEND 决定）:
  - sentence_transformers : 本地/在线中文模型（最佳，需模型可用）
  - chromadb              : ChromaDB 内置模型（离线可用，英文为主）
  - none                  : 关闭语义路由

设计原则:
  1. 懒加载 + 单例：首次调用才加载模型并预计算例句向量。
  2. 完全静默降级：模型不可用时 is_available()=False，绝不抛错影响主流程。
  3. 只做「建议」：输出带相似度分数，由 classify_intent 决定是否采纳。
=============================================================================
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from loguru import logger

from app.core.config import get_settings
from app.agent.intents import PrimaryIntent, SubIntent
from app.agent.intent_registry import get_all_examples

settings = get_settings()


@dataclass
class RouteResult:
    primary: PrimaryIntent
    sub: SubIntent
    score: float                     # 最高相似度 [0,1]
    margin: float                    # 与次高意图的分差（区分度）
    matched_example: str


class _EmbeddingProvider:
    """可插拔 embedding 封装，统一 encode(list[str])->list[vector] 接口。"""

    def __init__(self):
        self._backend = None         # 'st' | 'chroma' | None
        self._model = None
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        backend = settings.EMBEDDING_BACKEND.lower()

        # 1) sentence-transformers（中文最佳）
        if backend in ("auto", "sentence_transformers"):
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(settings.EMBEDDING_MODEL, device="cpu")
                self._backend = "st"
                logger.info(f"SemanticRouter embedding: sentence-transformers ({settings.EMBEDDING_MODEL})")
                return
            except Exception as e:
                logger.info(f"SemanticRouter: sentence-transformers unavailable ({str(e)[:80]})")
                if backend == "sentence_transformers":
                    return

        # 2) ChromaDB 内置（离线可用）
        if backend in ("auto", "chromadb"):
            try:
                from chromadb.utils import embedding_functions
                self._model = embedding_functions.DefaultEmbeddingFunction()
                # 触发一次实际加载，确认可用
                _ = self._model(["测试"])
                self._backend = "chroma"
                logger.info("SemanticRouter embedding: chromadb default (offline)")
                return
            except Exception as e:
                logger.info(f"SemanticRouter: chromadb embedding unavailable ({str(e)[:80]})")

        # 3) 关闭
        self._backend = None
        logger.info("SemanticRouter: embedding disabled (rule + LLM only)")

    def available(self) -> bool:
        self._load()
        return self._backend is not None

    def encode(self, texts: list[str]):
        """返回 numpy 数组 (n, dim)，不可用时返回 None。"""
        self._load()
        if self._backend is None:
            return None
        try:
            import numpy as np
            if self._backend == "st":
                vecs = self._model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
                return np.asarray(vecs, dtype="float32")
            else:  # chroma
                vecs = self._model(texts)
                arr = np.asarray(vecs, dtype="float32")
                # 归一化，便于用点积算余弦
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                norms[norms == 0] = 1.0
                return arr / norms
        except Exception as e:
            logger.warning(f"SemanticRouter encode failed: {e}")
            return None


class SemanticRouter:
    """基于注册表例句的语义路由器（单例）。"""

    def __init__(self):
        self._provider = _EmbeddingProvider()
        self._example_vecs = None            # (N, dim)
        self._example_meta: list[tuple[PrimaryIntent, SubIntent, str]] = []
        self._built = False
        self._lock = threading.Lock()

    def available(self) -> bool:
        return self._provider.available()

    def _ensure_index(self):
        if self._built:
            return
        with self._lock:
            if self._built:
                return
            if not self._provider.available():
                self._built = True
                return
            examples = get_all_examples()
            texts = [e[0] for e in examples]
            vecs = self._provider.encode(texts)
            if vecs is None:
                self._built = True
                return
            self._example_vecs = vecs
            self._example_meta = [(p, s, t) for (t, p, s) in examples]
            self._built = True
            logger.info(f"SemanticRouter index built: {len(texts)} example utterances")

    def route(self, text: str) -> RouteResult | None:
        """返回最相似意图；不可用或无有效结果时返回 None。"""
        if not text or not text.strip():
            return None
        self._ensure_index()
        if self._example_vecs is None:
            return None
        try:
            import numpy as np
            q = self._provider.encode([text.strip()])
            if q is None:
                return None
            sims = self._example_vecs @ q[0]          # 已归一化 → 点积=余弦
            best_idx = int(np.argmax(sims))
            best_score = float(sims[best_idx])
            best_primary, best_sub, best_ex = self._example_meta[best_idx]

            # 计算与「不同 primary」的次高分，得到区分度 margin
            second = 0.0
            for i, s in enumerate(sims):
                p, _, _ = self._example_meta[i]
                if p != best_primary and float(s) > second:
                    second = float(s)
            margin = best_score - second

            return RouteResult(
                primary=best_primary, sub=best_sub,
                score=best_score, margin=margin, matched_example=best_ex,
            )
        except Exception as e:
            logger.warning(f"SemanticRouter route failed: {e}")
            return None


# 全局单例
_router: SemanticRouter | None = None


def get_semantic_router() -> SemanticRouter:
    global _router
    if _router is None:
        _router = SemanticRouter()
    return _router
