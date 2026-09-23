# -*- coding: utf-8 -*-
"""应用工厂。

负责组装各层依赖、管理生命周期，是唯一把「配置」与「实现」连起来的地方。
"""
from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import __version__
from app.api import chat, documents, feedback, meta, pages, session
from app.config import Settings, get_settings
from app.core.logging import get_logger, setup_logging
from app.feedback.store import FeedbackStore
from app.ingest.repository import DocumentRepository
from app.llm.registry import create_provider
from app.retrieval.engine import HybridRetriever
from app.session.store import create_session_store

logger = get_logger(__name__)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """构建 FastAPI 应用。"""
    settings = settings or get_settings()
    setup_logging(settings.server.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        repository = DocumentRepository(
            settings.knowledge_base_dir, settings.upload_dir
        )
        retriever = HybridRetriever(settings.retrieval, data_dir=settings.data_dir)
        sessions = create_session_store(settings.session)
        provider = create_provider(settings.llm)
        feedback_store = FeedbackStore(
            settings.feedback.sqlite_path, enabled=settings.feedback.enabled
        )

        app.state.settings = settings
        app.state.repository = repository
        app.state.retriever = retriever
        app.state.sessions = sessions
        app.state.llm = provider
        app.state.feedback = feedback_store

        # BM25 建索引很快，同步完成；向量模型放后台预热，不阻塞启动。
        # 用守护线程是为了让进程能正常退出，不必等模型加载完。
        documents = repository.load_for_index()
        retriever.rebuild(documents)
        warm_thread = None
        if settings.retrieval.embedding.enabled and settings.retrieval.embedding.warmup:
            warm_thread = threading.Thread(
                target=retriever.warm, name="embedding-warmup", daemon=True
            )
            warm_thread.start()
            logger.info("向量模型将在后台预热")

        # 绑到 0.0.0.0 时浏览器无法直接访问该地址，日志里给出可点的本机地址
        display_host = "127.0.0.1" if settings.server.host in ("0.0.0.0", "::") else settings.server.host
        logger.info("服务就绪：http://%s:%d", display_host, settings.server.port)
        try:
            yield
        finally:
            await provider.aclose()
            sessions.close()
            feedback_store.close()

    app = FastAPI(
        title="agri-kb",
        description="新疆农业知识库 RAG 问答系统",
        version=__version__,
        lifespan=lifespan,
    )

    app.state.templates = Jinja2Templates(directory=str(settings.templates_dir))
    if settings.static_dir.exists():
        app.mount(
            "/static", StaticFiles(directory=str(settings.static_dir)), name="static"
        )

    app.include_router(pages.router)
    app.include_router(chat.router)
    app.include_router(documents.router)
    app.include_router(session.router)
    app.include_router(feedback.router)
    app.include_router(meta.router)
    return app
