# -*- coding: utf-8 -*-
"""
配置中心
========

所有可调参数集中在此定义，避免散落在业务代码里。
配置优先级（高 -> 低）：

1. 进程环境变量
2. 项目根目录 .env 文件
3. LLM 供应商预设（app.llm.presets）
4. 本模块的默认值
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from app.llm.presets import DEFAULT_PROVIDER, LLMPreset, get_preset

# 项目根目录（app/ 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent


# ==========================================================================
# 读取工具
# ==========================================================================

def parse_env_file(path: Path) -> Dict[str, str]:
    """解析 .env 文件；容忍 BOM、注释行、空行与包裹的引号。"""
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def _to_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _to_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


class EnvView:
    """对合并后的配置字典做带默认值的类型化读取。"""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)

    def get(self, key: str, default: Any = None) -> Any:
        value = self._values.get(key)
        return default if value is None or value == "" else value

    def str(self, key: str, default: str = "") -> str:
        return str(self.get(key, default))

    def bool(self, key: str, default: bool = False) -> bool:
        return _to_bool(self._values.get(key), default)

    def int(self, key: str, default: int = 0) -> int:
        return _to_int(self.get(key), default)

    def float(self, key: str, default: float = 0.0) -> float:
        return _to_float(self.get(key), default)

    def path(self, key: str, default: Path, base: Path) -> Path:
        raw = self.get(key)
        if not raw:
            return default
        path = Path(str(raw)).expanduser()
        return path if path.is_absolute() else (base / path)


# ==========================================================================
# 分组配置
# ==========================================================================

@dataclass(frozen=True)
class LLMSettings:
    """大模型调用参数。"""

    provider: str = DEFAULT_PROVIDER
    label: str = ""
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    temperature: float = 0.3
    max_tokens: int = 2048
    timeout: float = 60.0
    # 连接超时压到 5 秒：正常握手只要 0.1 秒左右，握手丢包时多等没有意义，
    # 快速失败 + 重试比死等一次更划算。
    connect_timeout: float = 5.0
    max_retries: int = 2
    keepalive_expiry: float = 300.0
    notes: str = ""

    @property
    def is_configured(self) -> bool:
        """三项齐全才算可用，缺一则向前端返回明确的配置指引。"""
        return bool(self.api_key and self.base_url and self.model)

    @property
    def missing(self) -> list:
        gaps = []
        if not self.base_url:
            gaps.append("base_url")
        if not self.model:
            gaps.append("model")
        if not self.api_key:
            gaps.append("api_key")
        return gaps


@dataclass(frozen=True)
class EmbeddingSettings:
    """向量检索参数。"""

    enabled: bool = True
    model_name: str = "BAAI/bge-small-zh-v1.5"
    warmup: bool = True                 # 启动后台预热，不阻塞服务启动
    cache_enabled: bool = True          # 向量落盘复用，避免每次重编码
    batch_size: int = 32
    hf_endpoint: str = ""               # HuggingFace 镜像，如 https://hf-mirror.com


@dataclass(frozen=True)
class RerankSettings:
    """重排（cross-encoder）参数。

    召回阶段（BM25 + 向量）只能算「大致相关」，重排模型会把问题和每个候选
    片段拼在一起做一次精细打分，把真正回答了问题的片段顶到前面。
    """

    # 默认关闭：重排模型约 1GB，让服务在启动时偷偷拉不合适。
    # 先用 python -m app.tools.prefetch_models 下好，再把它打开。
    enabled: bool = False
    model_name: str = "BAAI/bge-reranker-base"
    warmup: bool = True                 # 启动后台预热，不阻塞服务
    max_candidates: int = 20            # 只对前 N 个候选重排，控制耗时


@dataclass(frozen=True)
class RetrievalSettings:
    """检索参数。"""

    chunk_size: int = 400
    min_chunk_size: int = 80            # 小于该长度的碎片并入相邻片段
    top_k: int = 5
    candidate_multiplier: int = 3       # 粗排召回条数 = top_k * 该系数
    min_bm25_score: float = 0.01
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    bm25_weight: float = 0.3
    embedding_weight: float = 0.7
    normalize_scores: bool = True       # 融合前把 BM25 分数归一到 0~1
    max_chunks_per_document: int = 2    # 单篇文档最多贡献几个片段，保证来源多样性
    embedding: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    rerank: RerankSettings = field(default_factory=RerankSettings)


@dataclass(frozen=True)
class SessionSettings:
    """会话存储参数。"""

    backend: str = "json"               # json | sqlite
    max_sessions: int = 100
    history_window: int = 10            # 送入模型的历史条数
    json_path: Path = BASE_DIR / "data" / "conversations.json"
    sqlite_path: Path = BASE_DIR / "data" / "agri-kb.sqlite3"
    legacy_json_path: Path = BASE_DIR / "conversations.json"


@dataclass(frozen=True)
class FeedbackSettings:
    """用户反馈存储参数。"""

    enabled: bool = True
    sqlite_path: Path = BASE_DIR / "data" / "feedback.sqlite3"


@dataclass(frozen=True)
class ServerSettings:
    host: str = "0.0.0.0"
    port: int = 8000
    reload: bool = False
    log_level: str = "info"


@dataclass(frozen=True)
class Settings:
    """全局配置聚合。"""

    base_dir: Path = BASE_DIR
    knowledge_base_dir: Path = BASE_DIR / "knowledge_base"
    upload_dir: Path = BASE_DIR / "uploads"
    data_dir: Path = BASE_DIR / "data"
    static_dir: Path = BASE_DIR / "static"
    templates_dir: Path = BASE_DIR / "templates"
    max_upload_mb: int = 20
    llm: LLMSettings = field(default_factory=LLMSettings)
    retrieval: RetrievalSettings = field(default_factory=RetrievalSettings)
    session: SessionSettings = field(default_factory=SessionSettings)
    feedback: FeedbackSettings = field(default_factory=FeedbackSettings)
    server: ServerSettings = field(default_factory=ServerSettings)

    # ---------------------------------------------------------------- 构建

    @classmethod
    def load(
        cls,
        env_file: Optional[Path] = None,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "Settings":
        """按优先级合并配置并构造 Settings。"""
        env_file = env_file if env_file is not None else (BASE_DIR / ".env")
        merged: Dict[str, str] = parse_env_file(env_file)
        merged.update({k: v for k, v in dict(environ or os.environ).items() if v is not None})
        env = EnvView(merged)

        base = env.path("AGRI_BASE_DIR", BASE_DIR, BASE_DIR)
        data_dir = env.path("DATA_DIR", base / "data", base)

        # ---------------- LLM ----------------
        provider_key = env.str("LLM_PROVIDER", DEFAULT_PROVIDER).lower()
        preset: LLMPreset = get_preset(provider_key)
        prefix = provider_key.upper().replace("-", "_")
        # 供应商专用变量优先于通用变量，便于同时保留多家的 Key
        base_url = (
            env.str(f"{prefix}_BASE_URL", "")
            or env.str("LLM_BASE_URL", "")
            or preset.base_url
        )
        model = (
            env.str(f"{prefix}_MODEL", "")
            or env.str("LLM_MODEL", "")
            or preset.model
        )
        api_key = (
            env.str(f"{prefix}_API_KEY", "")
            or env.str("LLM_API_KEY", "")
            or env.str(preset.api_key_env, "")
        )
        llm = LLMSettings(
            provider=provider_key,
            label=preset.label,
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            model=model,
            temperature=env.float("LLM_TEMPERATURE", 0.3),
            max_tokens=env.int("LLM_MAX_TOKENS", 2048),
            timeout=env.float("LLM_TIMEOUT", 60.0),
            connect_timeout=env.float("LLM_CONNECT_TIMEOUT", 5.0),
            max_retries=env.int("LLM_MAX_RETRIES", 2),
            keepalive_expiry=env.float("LLM_KEEPALIVE_EXPIRY", 300.0),
            notes=preset.notes,
        )

        # ---------------- 向量模型 ----------------
        hf_endpoint = env.str("HF_ENDPOINT", "")
        if hf_endpoint:
            # huggingface_hub 读的是进程环境变量，这里补齐（写在 .env 里也算数）
            os.environ.setdefault("HF_ENDPOINT", hf_endpoint)
            # 新版 huggingface_hub 默认用 Xet 协议传大文件，而国内镜像不代理
            # Xet，会以 401 Unauthorized 失败。走镜像时强制退回普通 HTTP 下载。
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        # 模型缓存默认放在项目 data/ 下：部署可复现、离线可复用，
        # 也不会因为用户主目录不可写而加载失败。显式设置 HF_HOME 可覆盖。
        hf_home = env.str("HF_HOME", str(data_dir / "hf_cache"))
        os.environ.setdefault("HF_HOME", hf_home)
        if os.name == "nt":
            # Windows 上默认不支持符号链接，这条只是关掉 huggingface_hub 的提示
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        embedding = EmbeddingSettings(
            enabled=env.bool("EMBED_ENABLED", True),
            model_name=env.str("EMBED_MODEL", "BAAI/bge-small-zh-v1.5"),
            warmup=env.bool("EMBED_WARMUP", True),
            cache_enabled=env.bool("EMBED_CACHE", True),
            batch_size=env.int("EMBED_BATCH_SIZE", 32),
            hf_endpoint=hf_endpoint,
        )
        rerank = RerankSettings(
            enabled=env.bool("RERANK_ENABLED", False),
            model_name=env.str("RERANK_MODEL", "BAAI/bge-reranker-base"),
            warmup=env.bool("RERANK_WARMUP", True),
            max_candidates=env.int("RERANK_MAX_CANDIDATES", 20),
        )

        # ---------------- 检索 ----------------
        retrieval = RetrievalSettings(
            chunk_size=env.int("RAG_CHUNK_SIZE", 400),
            min_chunk_size=env.int("RAG_MIN_CHUNK_SIZE", 80),
            top_k=env.int("RAG_TOP_K", 5),
            candidate_multiplier=env.int("RAG_CANDIDATE_MULTIPLIER", 3),
            min_bm25_score=env.float("RAG_MIN_BM25_SCORE", 0.01),
            bm25_k1=env.float("RAG_BM25_K1", 1.5),
            bm25_b=env.float("RAG_BM25_B", 0.75),
            bm25_weight=env.float("RAG_BM25_WEIGHT", 0.3),
            embedding_weight=env.float("RAG_EMBED_WEIGHT", 0.7),
            normalize_scores=env.bool("RAG_NORMALIZE_SCORES", True),
            max_chunks_per_document=env.int("RAG_MAX_CHUNKS_PER_DOC", 2),
            embedding=embedding,
            rerank=rerank,
        )

        # ---------------- 会话 ----------------
        session = SessionSettings(
            backend=env.str("SESSION_BACKEND", "json").lower(),
            max_sessions=env.int("SESSION_MAX", 100),
            history_window=env.int("SESSION_HISTORY_WINDOW", 10),
            json_path=env.path("SESSION_JSON_PATH", data_dir / "conversations.json", base),
            sqlite_path=env.path("SESSION_SQLITE_PATH", data_dir / "agri-kb.sqlite3", base),
            legacy_json_path=base / "conversations.json",
        )

        # ---------------- 服务 ----------------
        feedback = FeedbackSettings(
            enabled=env.bool("FEEDBACK_ENABLED", True),
            sqlite_path=env.path("FEEDBACK_DB_PATH", data_dir / "feedback.sqlite3", base),
        )

        server = ServerSettings(
            host=env.str("HOST", "0.0.0.0"),
            port=env.int("PORT", 8000),
            reload=env.bool("RELOAD", False),
            log_level=env.str("LOG_LEVEL", "info"),
        )

        return cls(
            base_dir=base,
            knowledge_base_dir=env.path("KB_DIR", base / "knowledge_base", base),
            upload_dir=env.path("UPLOAD_DIR", base / "uploads", base),
            data_dir=data_dir,
            static_dir=base / "static",
            templates_dir=base / "templates",
            max_upload_mb=env.int("MAX_UPLOAD_MB", 20),
            llm=llm,
            retrieval=retrieval,
            session=session,
            feedback=feedback,
            server=server,
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例配置。测试可用 reset_settings() 清缓存。"""
    return Settings.load()


def reset_settings() -> None:
    """清除配置缓存（主要用于测试）。"""
    get_settings.cache_clear()
