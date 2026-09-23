# -*- coding: utf-8 -*-
"""
混合检索引擎
============

流程：BM25 粗排召回候选 -> 向量语义精排 -> 加权融合 -> 来源去重。

融合前会先把 BM25 分数做 min-max 归一化，否则 BM25 的无界分数与
余弦相似度（0~1）直接加权没有可比性。
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from app.config import RetrievalSettings
from app.core.logging import get_logger
from app.retrieval.bm25 import BM25Index, SearchHit
from app.retrieval.embedding import EmbeddingModel
from app.retrieval.reranker import CrossEncoderReranker

logger = get_logger(__name__)


class HybridRetriever:
    """BM25 + 向量的混合检索器，对外只暴露 rebuild / warm / search。"""

    def __init__(self, settings: RetrievalSettings, data_dir: Optional[Path] = None) -> None:
        self.settings = settings
        self.bm25 = BM25Index(
            k1=settings.bm25_k1,
            b=settings.bm25_b,
            min_score=settings.min_bm25_score,
        )
        self.embedding = EmbeddingModel(settings.embedding, cache_dir=data_dir)
        self.reranker = CrossEncoderReranker(settings.rerank)
        self._vectors = None
        self._document_count = 0

    # ------------------------------------------------------------------ 索引

    def rebuild(self, docs: Sequence[dict], eager_vectors: bool = False) -> Tuple[int, int]:
        """重建全部索引，返回 (文档数, 片段数)。

        默认不主动加载向量模型，避免网络下载阻塞服务启动；向量由
        :meth:`warm` 在后台线程里补建。若模型已就绪则顺手算掉。
        """
        self.bm25.build(
            docs,
            chunk_size=self.settings.chunk_size,
            min_chunk_size=self.settings.min_chunk_size,
        )
        self._document_count = len(docs)
        self._vectors = None
        if eager_vectors or self.embedding.available:
            self._build_vectors()
        logger.info(
            "索引重建完成：%d 篇文档 / %d 个片段 / 向量%s",
            self._document_count,
            len(self.bm25.chunks),
            "已就绪" if self._vectors is not None else "未启用",
        )
        return self._document_count, len(self.bm25.chunks)

    def warm(self) -> None:
        """预热向量模型（供启动时在后台线程调用，不阻塞服务）。"""
        if self.settings.embedding.enabled:
            self._build_vectors()
        if self.settings.rerank.enabled:
            self.reranker.ensure_loaded()

    def _build_vectors(self) -> bool:
        """为所有片段预计算向量，返回是否成功。"""
        if not self.bm25.chunks or not self.settings.embedding.enabled:
            self._vectors = None
            return False
        if not self.embedding.available and not self.embedding.ensure_loaded():
            self._vectors = None
            return False
        self._vectors = self.embedding.encode_documents([c.text for c in self.bm25.chunks])
        return self._vectors is not None

    # ------------------------------------------------------------------ 检索

    def search(self, query: str, top_k: Optional[int] = None) -> List[SearchHit]:
        """混合检索，返回至多 top_k 条命中。"""
        top_k = top_k or self.settings.top_k
        if not self.bm25.chunks:
            return []

        # 1) 粗排：多召回一些候选交给精排
        candidate_n = min(
            max(top_k * max(self.settings.candidate_multiplier, 1), top_k),
            len(self.bm25.chunks),
        )
        candidates = self.bm25.search(query, top_k=candidate_n)
        if not candidates:
            return []

        # 2) 精排：向量可用时按权重融合
        #    请求路径上不主动加载模型（首个请求可能等上十几秒）；
        #    冷启动由 warm() 在后台完成，只有显式关闭预热时才走懒加载。
        if self._vectors is None and (
            self.embedding.available or not self.settings.embedding.warmup
        ):
            self._build_vectors()
        if self._vectors is not None:
            query_vector = self.embedding.encode_query(query)
            if query_vector is not None:
                self._apply_embedding_scores(candidates, query_vector)

        # 3) 按融合分排序
        candidates.sort(key=lambda h: h.score, reverse=True)

        # 4) 重排：把真正回答了问题的片段顶到前面
        candidates = self._apply_rerank(query, candidates)

        # 5) 来源去重后返回
        return self._diversify(candidates, top_k)

    def _apply_rerank(self, query: str, hits: List[SearchHit]) -> List[SearchHit]:
        """重排候选；模型未就绪时原样返回（与向量检索同一套降级策略）。"""
        if not self.settings.rerank.enabled:
            return hits
        # 请求路径不主动加载模型：冷启动交给 warm() 在后台完成，
        # 只有显式关闭预热时才允许在这里懒加载。
        if not self.reranker.available and self.settings.rerank.warmup:
            return hits
        return self.reranker.rerank(query, hits)

    def _apply_embedding_scores(self, hits: List[SearchHit], query_vector) -> None:
        """计算余弦相似度并做加权融合。"""
        import numpy as np

        weight_bm25 = self.settings.bm25_weight
        weight_embed = self.settings.embedding_weight
        total = (weight_bm25 + weight_embed) or 1.0

        raw = [h.bm25_score for h in hits]
        low, high = min(raw), max(raw)
        span = high - low

        for hit in hits:
            if self.settings.normalize_scores:
                hit.bm25_norm = 1.0 if span <= 0 else (hit.bm25_score - low) / span
            else:
                hit.bm25_norm = hit.bm25_score
            if 0 <= hit.index < len(self._vectors):
                cosine = float(np.dot(query_vector, self._vectors[hit.index]))
                hit.embedding_score = max(0.0, min(1.0, cosine))
            else:
                hit.embedding_score = 0.0
            hit.score = (
                weight_bm25 * hit.bm25_norm + weight_embed * hit.embedding_score
            ) / total

    def _diversify(self, hits: List[SearchHit], top_k: int) -> List[SearchHit]:
        """限制单篇文档贡献的片段数量，让参考来源更分散。"""
        limit = self.settings.max_chunks_per_document
        if limit <= 0:
            return hits[:top_k]
        used = {}
        picked: List[SearchHit] = []
        for hit in hits:
            count = used.get(hit.filename, 0)
            if count >= limit:
                continue
            used[hit.filename] = count + 1
            picked.append(hit)
            if len(picked) >= top_k:
                break
        if len(picked) < top_k:                 # 去重后不足则用剩余结果补齐
            for hit in hits:
                if hit not in picked:
                    picked.append(hit)
                if len(picked) >= top_k:
                    break
        return picked

    # ------------------------------------------------------------------ 元信息

    @property
    def document_count(self) -> int:
        return self._document_count

    @property
    def chunk_count(self) -> int:
        return len(self.bm25.chunks)

    @property
    def vector_ready(self) -> bool:
        return self._vectors is not None

    def stats(self) -> dict:
        stats = {
            "documents": self._document_count,
            "chunks": self.chunk_count,
            "terms": self.bm25.term_count,
            "avg_chunk_terms": round(self.bm25.avgdl, 1),
            "embedding_enabled": self.settings.embedding.enabled,
            "embedding_ready": self.vector_ready,
            "embedding_model": self.settings.embedding.model_name,
        }
        stats.update(self.reranker.stats())
        return stats
