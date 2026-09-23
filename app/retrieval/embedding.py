# -*- coding: utf-8 -*-
"""
向量化模型封装
==============

设计要点：
  * 延迟加载：首次真正用到时才导入模型，不拖慢服务启动；
  * 失败熔断：加载失败只尝试一次，之后直接降级为纯 BM25，不反复重试；
  * 结果缓存：向量按内容指纹落盘，重启或重建索引时可直接复用。
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional, Sequence

from app.config import EmbeddingSettings
from app.core.logging import get_logger

logger = get_logger(__name__)

try:                                    # numpy 与 sentence-transformers 均为可选依赖
    import numpy as np
except ImportError:                     # pragma: no cover
    np = None

# sentence-transformers 会连带导入 torch，耗时可达十几秒。
# 这里只在真正需要向量时才 import，避免拖慢服务启动。
_ST_CLASS = None                        # None=未探测，False=不可用，否则为类对象
_ST_PROBED = False


def _sentence_transformer_class():
    """按需导入 SentenceTransformer，结果缓存，失败只探测一次。"""
    global _ST_CLASS, _ST_PROBED
    if not _ST_PROBED:
        try:
            from sentence_transformers import SentenceTransformer
            _ST_CLASS = SentenceTransformer
        except ImportError:             # pragma: no cover
            _ST_CLASS = False
        _ST_PROBED = True
    return _ST_CLASS


class EmbeddingModel:
    """BGE 等句向量模型的外层封装。"""

    def __init__(self, settings: EmbeddingSettings, cache_dir: Optional[Path] = None) -> None:
        self.settings = settings
        self.cache_dir = cache_dir
        self._model = None
        self._load_failed = False

    # ------------------------------------------------------------------ 可用性

    @property
    def enabled(self) -> bool:
        """向量能力是否可用（会按需探测依赖是否安装）。"""
        return bool(
            self.settings.enabled
            and np is not None
            and _sentence_transformer_class()
        )

    @property
    def available(self) -> bool:
        """模型是否已就绪（不会触发加载）。"""
        return self._model is not None

    def _local_snapshot(self) -> Optional[str]:
        """
        在 HF_HOME 缓存里查找已经下载好的模型快照。

        找到就直接用本地目录加载，完全不联网——否则 huggingface_hub 每次
        都会去校验一遍远端文件，网络不通时要卡很久（本项目在国内网络下的常见现象）。
        """
        # 配置项直接指向本地目录（手动下载的场景）
        configured = Path(self.settings.model_name).expanduser()
        if configured.is_dir():
            return str(configured)

        hf_home = os.environ.get("HF_HOME")
        root = Path(hf_home) if hf_home else Path.home() / ".cache" / "huggingface"
        repo_dir = root / "hub" / ("models--" + self.settings.model_name.replace("/", "--"))
        snapshots = repo_dir / "snapshots"
        if not snapshots.is_dir():
            return None
        for snapshot in sorted(snapshots.iterdir(), reverse=True):
            if not snapshot.is_dir():
                continue
            if (snapshot / "modules.json").exists() or (snapshot / "config.json").exists():
                return str(snapshot)
        return None

    def ensure_loaded(self) -> bool:
        """确保模型已加载；返回是否可用。失败只尝试一次。"""
        if self._model is not None:
            return True
        if self._load_failed or not self.enabled:
            return False

        model_class = _sentence_transformer_class()
        local_snapshot = self._local_snapshot()
        # 优先本地快照（零网络），失败再退回按模型名加载（会联网）
        attempts = []
        if local_snapshot:
            attempts.append((local_snapshot, True))
        attempts.append((self.settings.model_name, False))

        last_error = None
        logger.info("正在加载向量模型：%s", self.settings.model_name)
        for target, local_only in attempts:
            try:
                self._model = model_class(target, local_files_only=local_only)
                if local_snapshot and local_only:
                    logger.info("向量模型来自本地缓存，未发起网络请求")
                break
            except Exception as exc:
                last_error = exc

        if self._model is not None:
            dimension = getattr(self._model, "get_embedding_dimension", None) or getattr(
                self._model, "get_sentence_embedding_dimension", None
            )
            logger.info("向量模型加载完成，维度 %s", dimension() if dimension else "未知")
            return True

        self._load_failed = True
        hint = ""
        if not self.settings.hf_endpoint:
            hint = "；国内网络可在 .env 设置 HF_ENDPOINT=https://hf-mirror.com"
        logger.warning("向量模型不可用，已降级为纯 BM25 检索：%s%s", last_error, hint)
        return False

    # ------------------------------------------------------------------ 编码

    def encode_documents(self, texts: Sequence[str]):
        """批量编码文档片段（带落盘缓存）。"""
        if not self.ensure_loaded():
            return None
        cached = self._load_cache(texts)
        if cached is not None:
            return cached
        try:
            vectors = self._model.encode(
                list(texts),
                batch_size=self.settings.batch_size,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        except Exception as exc:
            logger.warning("文档向量化失败：%s", exc)
            return None
        self._save_cache(texts, vectors)
        return vectors

    def encode_query(self, text: str):
        """编码单条查询。"""
        if not self.ensure_loaded():
            return None
        try:
            return self._model.encode([text], normalize_embeddings=True)[0]
        except Exception as exc:
            logger.warning("查询向量化失败：%s", exc)
            return None

    # ------------------------------------------------------------------ 缓存

    def _cache_paths(self):
        if not (self.settings.cache_enabled and self.cache_dir):
            return None, None
        return (
            self.cache_dir / "embedding_cache.npz",
            self.cache_dir / "embedding_cache.json",
        )

    @staticmethod
    def _signature(texts: Sequence[str], model_name: str) -> str:
        digest = hashlib.sha256(model_name.encode("utf-8"))
        for text in texts:
            digest.update(text.encode("utf-8", errors="ignore"))
        return digest.hexdigest()

    def _load_cache(self, texts: Sequence[str]):
        vectors_path, meta_path = self._cache_paths()
        if not vectors_path or not vectors_path.exists() or not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("signature") != self._signature(texts, self.settings.model_name):
                return None
            vectors = np.load(vectors_path)["vectors"]
            if len(vectors) != len(texts):
                return None
            logger.info("复用向量缓存：%d 条", len(texts))
            return vectors
        except Exception:
            return None

    def _save_cache(self, texts: Sequence[str], vectors) -> None:
        vectors_path, meta_path = self._cache_paths()
        if not vectors_path:
            return
        try:
            vectors_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(vectors_path, vectors=vectors)
            meta_path.write_text(
                json.dumps(
                    {
                        "signature": self._signature(texts, self.settings.model_name),
                        "model": self.settings.model_name,
                        "count": len(texts),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("写入向量缓存失败：%s", exc)
