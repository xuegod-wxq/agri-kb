# -*- coding: utf-8 -*-
"""依赖注入：从 app.state 取各层实例。"""
from __future__ import annotations

from fastapi import Request

from app.config import Settings
from app.feedback.store import FeedbackStore
from app.ingest.repository import DocumentRepository
from app.llm.base import LLMProvider
from app.retrieval.engine import HybridRetriever
from app.session.store import SessionStore


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_repository(request: Request) -> DocumentRepository:
    return request.app.state.repository


def get_retriever(request: Request) -> HybridRetriever:
    return request.app.state.retriever


def get_session_store(request: Request) -> SessionStore:
    return request.app.state.sessions


def get_llm_provider(request: Request) -> LLMProvider:
    return request.app.state.llm


def get_feedback_store(request: Request) -> FeedbackStore:
    return request.app.state.feedback
