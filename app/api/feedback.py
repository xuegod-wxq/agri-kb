# -*- coding: utf-8 -*-
"""用户反馈接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_feedback_store, get_llm_provider, get_settings_dep
from app.config import Settings
from app.feedback.store import FeedbackStore
from app.llm.base import LLMProvider
from app.schemas import FeedbackRequest

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


@router.post("")
async def submit_feedback(
    payload: FeedbackRequest,
    store: FeedbackStore = Depends(get_feedback_store),
    provider: LLMProvider = Depends(get_llm_provider),
    settings: Settings = Depends(get_settings_dep),
):
    """
    记录一条 👍 / 👎。

    点踩的案例最有价值：它们是「当前检索/提示词做得不好」的真实样本，
    可以捞出来补进 tests/eval_set.json 当评测题。
    """
    if not settings.feedback.enabled:
        return {"status": "disabled"}
    try:
        feedback_id = store.add(
            question=payload.question,
            answer=payload.answer,
            rating=payload.rating,
            sources=payload.sources,
            session_id=payload.session_id,
            comment=payload.comment,
            provider=provider.name,
            model=provider.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "id": feedback_id}


@router.get("/stats")
async def feedback_stats(store: FeedbackStore = Depends(get_feedback_store)):
    """好评率概览。"""
    return store.stats()


@router.get("/recent")
async def feedback_recent(
    store: FeedbackStore = Depends(get_feedback_store),
    limit: int = Query(20, ge=1, le=200),
    rating: str = Query("", description="留空看全部，down 只看点踩"),
):
    """最近的反馈明细，用于人工复盘。"""
    return {"items": store.recent(limit=limit, rating=rating or None)}
