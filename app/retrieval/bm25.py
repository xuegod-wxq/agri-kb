# -*- coding: utf-8 -*-
"""BM25 关键词检索。"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Sequence

from app.retrieval.tokenizer import ChineseTokenizer


@dataclass
class SearchHit:
    """一条检索命中结果。"""

    index: int                      # 片段下标，与向量数组一一对应
    filename: str
    text: str
    score: float = 0.0              # 最终排序分数
    bm25_score: float = 0.0
    bm25_norm: float = 0.0          # 归一化后的 BM25 分数
    embedding_score: float = 0.0
    rerank_score: float = 0.0       # cross-encoder 打分（启用重排时才有）


@dataclass
class Chunk:
    """一个文本片段。"""

    index: int
    filename: str
    text: str


class BM25Index:
    """
    BM25 倒排索引。

    参数：
        k1  词频饱和系数（越大，词频影响越强）
        b   文档长度归一化系数（0 不归一化，1 完全归一化）

    打分公式：
        score(q, d) = Σ IDF(t) * f(t,d)*(k1+1) / ( f(t,d) + k1*(1-b+b*|d|/avgdl) )
    """

    def __init__(
        self,
        tokenizer: ChineseTokenizer = None,
        k1: float = 1.5,
        b: float = 0.75,
        min_score: float = 0.01,
    ) -> None:
        self.tokenizer = tokenizer or ChineseTokenizer()
        self.k1 = k1
        self.b = b
        self.min_score = min_score
        self.chunks: List[Chunk] = []
        self._doc_len: List[int] = []
        self._avgdl: float = 1.0
        self._idf: Dict[str, float] = {}
        self._tf: List[Dict[str, int]] = []

    # ------------------------------------------------------------------ 构建

    def build(
        self,
        docs: Sequence[dict],
        chunk_size: int = 400,
        min_chunk_size: int = 80,
    ) -> None:
        """用文档列表重建索引。docs 元素形如 {'filename': ..., 'text': ...}。"""
        from app.retrieval.chunker import chunk_text

        self.chunks = []
        for doc in docs:
            filename = doc.get("filename", "")
            for piece in chunk_text(
                doc.get("text", ""), size=chunk_size, min_size=min_chunk_size
            ):
                self.chunks.append(Chunk(index=len(self.chunks), filename=filename, text=piece))

        if not self.chunks:
            self._doc_len, self._avgdl, self._idf, self._tf = [], 1.0, {}, []
            return

        tokenized = [self.tokenizer.tokenize(c.text) for c in self.chunks]
        self._doc_len = [len(t) for t in tokenized]
        total = sum(self._doc_len)
        self._avgdl = (total / len(self.chunks)) if total else 1.0

        df: Dict[str, int] = defaultdict(int)
        for tokens in tokenized:
            for term in set(tokens):
                df[term] += 1

        n_docs = len(self.chunks)
        self._idf = {
            term: math.log((n_docs - freq + 0.5) / (freq + 0.5) + 1.0)
            for term, freq in df.items()
        }

        self._tf = []
        for tokens in tokenized:
            counter: Dict[str, int] = defaultdict(int)
            for term in tokens:
                counter[term] += 1
            self._tf.append(dict(counter))

    # ------------------------------------------------------------------ 检索

    def search(self, query: str, top_k: int = 3) -> List[SearchHit]:
        """返回 top_k 个命中片段（按 BM25 分数降序）。"""
        if not self.chunks:
            return []

        query_tf: Dict[str, int] = defaultdict(int)
        for term in self.tokenizer.tokenize(query):
            query_tf[term] += 1

        scored: List[SearchHit] = []
        for i, chunk in enumerate(self.chunks):
            dl = self._doc_len[i]
            tf = self._tf[i]
            score = 0.0
            for term, qtf in query_tf.items():
                freq = tf.get(term, 0)
                if freq == 0:
                    continue
                idf = self._idf.get(term)
                if idf is None:
                    continue
                denom = freq + self.k1 * (1 - self.b + self.b * dl / self._avgdl)
                score += idf * (freq * (self.k1 + 1) / denom) * qtf
            if score > self.min_score:
                scored.append(
                    SearchHit(
                        index=chunk.index,
                        filename=chunk.filename,
                        text=chunk.text,
                        score=score,
                        bm25_score=score,
                    )
                )

        scored.sort(key=lambda h: h.bm25_score, reverse=True)
        return scored[:top_k]

    # ------------------------------------------------------------------ 元信息

    @property
    def avgdl(self) -> float:
        return self._avgdl

    @property
    def term_count(self) -> int:
        return len(self._idf)
