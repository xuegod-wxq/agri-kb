# -*- coding: utf-8 -*-
"""重排模型封装（cross-encoder）。

召回阶段用的是「双塔」结构：问题和文档分别编码再算相似度，快但粗。
cross-encoder 把问题和候选片段拼成一条输入一起过模型，能真正判断
「这段话到底回不回答这个问题」，代价是慢——所以只对召回的少量候选使用。

与向量模型一样采取延迟加载 + 失败熔断 + 不可用即跳过的策略。
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Sequence

from app.config import RerankSettings
from app.core.logging import get_logger

logger = get_logger(__name__)

try:
    import numpy as np
except ImportError:                     # pragma: no cover
    np = None

# CrossEncoder 会连带导入 torch（十几秒），按需加载
_CROSS_ENCODER = None
_PROBED = False


def _cross_encoder_class():
    """按需导入 CrossEncoder，结果缓存，失败只探测一次。"""
    global _CROSS_ENCODER, _PROBED
    if not _PROBED:
        try:
            from sentence_transformers import CrossEncoder
            _CROSS_ENCODER = CrossEncoder
        except ImportError:             # pragma: no cover
            _CROSS_ENCODER = False
        _PROBED = True
    return _CROSS_ENCODER


def _sigmoid(x: float) -> float:
    """把模型原始 logit 压到 0~1，便于阅读和阈值判断。"""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


class CrossEncoderReranker:
    """基于 cross-encoder 的重排器。"""

    def __init__(self, settings: RerankSettings) -> None:
        self.settings = settings
        self._model = None
        self._load_failed = False

    # ------------------------------------------------------------------ 可用性

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled and np is not None and _cross_encoder_class())

    @property
    def available(self) -> bool:
        """模型是否已就绪（不会触发加载）。"""
        return self._model is not None

    def ensure_loaded(self) -> bool:
        """加载模型；失败只尝试一次，之后永久降级。"""
        if self._model is not None:
            return True
        if self._load_failed or not self.enabled:
            return False

        # 手动下载的场景：配置项直接指向本地模型目录时不联网
        target = self.settings.model_name
        local_only = False
        if Path(target).expanduser().is_dir():
            target = str(Path(target).expanduser())
            local_only = True
            logger.info("重排模型使用本地目录：%s", target)

        try:
            logger.info("正在加载重排模型：%s", self.settings.model_name)
            model_class = _cross_encoder_class()
            self._model = model_class(target, local_files_only=local_only)
            logger.info("重排模型加载完成")
            return True
        except Exception as exc:
            self._load_failed = True
            logger.warning("重排模型不可用，将跳过重排：%s", exc)
            return False

    # ------------------------------------------------------------------ 重排

    def rerank(self, query: str, hits: Sequence) -> List:
        """
        对候选片段重新打分并排序。

        hits: 具备 .text 属性的检索命中对象，会就地写入 rerank_score。
        """
        if not hits:
            return list(hits)
        if not self.available and not self.ensure_loaded():
            return list(hits)

        candidates = list(hits)[: self.settings.max_candidates]
        pairs = [(query, hit.text) for hit in candidates]
        try:
            raw_scores = self._model.predict(pairs, show_progress_bar=False)
        except Exception as exc:
            logger.warning("重排打分失败，保留原有顺序：%s", exc)
            return list(hits)

        for hit, raw in zip(candidates, raw_scores):
            hit.rerank_score = _sigmoid(float(raw))
            hit.score = hit.rerank_score    # score 始终代表最终排序依据

        candidates.sort(key=lambda h: h.rerank_score, reverse=True)
        # 未参与重排的候选（超出 max_candidates 的部分）排在后面
        rest = [h for h in hits if h not in candidates]
        return candidates + rest

    # ------------------------------------------------------------------ 元信息

    def stats(self) -> dict:
        return {
            "rerank_enabled": self.settings.enabled,
            "rerank_ready": self.available,
            "rerank_model": self.settings.model_name,
        }
