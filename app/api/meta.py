# -*- coding: utf-8 -*-
"""健康检查与元信息接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import (
    get_feedback_store,
    get_llm_provider,
    get_retriever,
    get_session_store,
    get_settings_dep,
)
from app.config import Settings
from app.feedback.store import FeedbackStore
from app.llm.base import LLMProvider
from app.llm.presets import list_presets
from app.retrieval.engine import HybridRetriever
from app.session.store import SessionStore

router = APIRouter(tags=["meta"])


@router.get("/health")
async def health(
    retriever: HybridRetriever = Depends(get_retriever),
    sessions: SessionStore = Depends(get_session_store),
    provider: LLMProvider = Depends(get_llm_provider),
):
    """存活探针：同时暴露索引与模型状态，便于排障。"""
    stats = retriever.stats()
    return {
        "status": "ok",
        "documents": stats["documents"],
        "chunks": stats["chunks"],
        "sessions": sessions.count(),
        "embedding_ready": stats["embedding_ready"],
        "llm": provider.describe(),
    }


@router.get("/api/stats")
async def stats(
    retriever: HybridRetriever = Depends(get_retriever),
    sessions: SessionStore = Depends(get_session_store),
    feedback_store: FeedbackStore = Depends(get_feedback_store),
    provider: LLMProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings_dep),
):
    """系统统计（前端统计弹窗使用）。"""
    return {
        "retrieval": retriever.stats(),
        "sessions": sessions.count(),
        "feedback": feedback_store.stats(),
        "llm": provider.describe(),
        "session_backend": settings.session.backend,
        "knowledge_base_dir": str(settings.knowledge_base_dir),
        "upload_dir": str(settings.upload_dir),
    }


@router.get("/api/providers")
async def providers(
    provider: LLMProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings_dep),
):
    """可选的大模型供应商与当前生效配置。"""
    return {
        "current": {
            **provider.describe(),
            "notes": settings.llm.notes,
            "missing": settings.llm.missing,
        },
        "available": list_presets(),
    }
