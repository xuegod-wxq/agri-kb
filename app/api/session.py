# -*- coding: utf-8 -*-
"""会话历史接口。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_session_store
from app.schemas import SessionHistory, SessionResetRequest
from app.session.store import SessionStore

router = APIRouter(prefix="/api/session", tags=["session"])


@router.post("/reset")
async def reset_session(
    payload: SessionResetRequest,
    sessions: SessionStore = Depends(get_session_store),
):
    """清空指定会话的对话历史。"""
    cleared = sessions.reset(payload.session_id) if payload.session_id else False
    return {"status": "ok", "cleared": cleared}


@router.get("/{session_id}", response_model=SessionHistory)
async def get_session(
    session_id: str,
    sessions: SessionStore = Depends(get_session_store),
):
    """取指定会话的历史消息（用于页面刷新后恢复上下文）。"""
    return SessionHistory(session_id=session_id, messages=sessions.get(session_id))
