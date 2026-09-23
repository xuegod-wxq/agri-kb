# -*- coding: utf-8 -*-
"""核心接口：RAG 流式问答。"""
from __future__ import annotations

import json
from typing import List

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import (
    get_llm_provider,
    get_repository,
    get_retriever,
    get_session_store,
    get_settings_dep,
)
from app.config import Settings
from app.core.logging import get_logger
from app.core.prompts import build_context, build_messages
from app.ingest.repository import DocumentRepository
from app.llm.base import LLMError, LLMProvider
from app.retrieval.engine import HybridRetriever
from app.schemas import ChatRequest
from app.session.store import SessionStore

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])

# SSE 响应头：X-Accel-Buffering 关闭 nginx 缓冲，否则前端拿不到逐字输出
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse(payload: dict) -> str:
    """把字典序列化成一条 SSE 消息。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _config_error_text(settings: Settings) -> str:
    """供应商未配置时给出可直接照做的提示。"""
    missing = "、".join(settings.llm.missing)
    text = (
        f"大模型尚未配置完成：{settings.llm.label or settings.llm.provider} "
        f"缺少 {missing}。请在项目根目录的 .env 中补齐后重启服务。"
    )
    if settings.llm.notes:
        text += f"\n\n说明：{settings.llm.notes}"
    return text


async def _error_only_stream(message: str):
    """只返回一条错误事件的 SSE 流。"""
    yield _sse({"type": "error", "data": message})
    yield "data: [DONE]\n\n"


@router.post("/chat/stream")
async def chat_stream(
    payload: ChatRequest,
    settings: Settings = Depends(get_settings_dep),
    retriever: HybridRetriever = Depends(get_retriever),
    repository: DocumentRepository = Depends(get_repository),
    sessions: SessionStore = Depends(get_session_store),
    provider: LLMProvider = Depends(get_llm_provider),
):
    """
    RAG 流式问答。

    流程：检索知识片段 -> 组装提示词 -> 调用 LLM 流式生成 -> SSE 推送。

    SSE 事件格式::

        data: {"type": "sources", "data": [...]}
        data: {"type": "chunk",   "data": "文本片段"}
        data: {"type": "error",   "data": "错误信息"}
        data: [DONE]
    """
    session_id = payload.session_id or "default"

    if not provider.is_configured():
        return StreamingResponse(
            _error_only_stream(_config_error_text(settings)),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    # 1) 检索：BM25 粗排 + 向量精排
    hits = retriever.search(payload.message, top_k=settings.retrieval.top_k)
    titles = {d["filename"]: d["title"] for d in repository.list_documents()}
    sources: List[dict] = [
        {
            "filename": hit.filename,
            "title": titles.get(hit.filename, hit.filename),
            "score": round(hit.score, 3),
        }
        for hit in hits
    ]

    # 2) 组装提示词：历史窗口 + 本轮参考资料
    history = sessions.get(session_id)
    messages = build_messages(
        payload.message,
        build_context(hits, titles),
        history,
        settings.session.history_window,
    )
    sessions.append(session_id, {"role": "user", "content": payload.message})

    # 3) 流式生成并落库
    async def generate():
        yield _sse({"type": "sources", "data": sources})
        answer = ""
        try:
            async for delta in provider.stream_chat(messages):
                answer += delta
                yield _sse({"type": "chunk", "data": delta})
        except LLMError as exc:
            logger.warning("模型调用失败：%s", exc)
            yield _sse({"type": "error", "data": str(exc)})
        except Exception as exc:                      # 兜底，避免连接被挂死
            logger.exception("问答流程异常")
            yield _sse({"type": "error", "data": f"服务异常：{exc}"})
        if answer:
            sessions.append(session_id, {"role": "assistant", "content": answer})
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers=SSE_HEADERS
    )
