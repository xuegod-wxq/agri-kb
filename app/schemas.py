# -*- coding: utf-8 -*-
"""API 出入参模型。"""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """流式问答请求体。"""

    message: str = Field(..., description="用户问题")
    session_id: str = Field("", description="会话标识，用于关联多轮上下文")


class SessionResetRequest(BaseModel):
    """清空会话请求体。"""

    session_id: str = Field("", description="要清空的会话标识")


class DocumentInfo(BaseModel):
    """文档摘要。"""

    title: str
    filename: str
    size: int
    source: str = "knowledge_base"


class DocumentDetail(BaseModel):
    """文档全文。"""

    name: str
    filename: str
    content: str


class UploadResponse(BaseModel):
    """上传结果。"""

    status: str = "ok"
    filename: str
    docs: int
    chunks: int


class SessionHistory(BaseModel):
    """会话历史。"""

    session_id: str
    messages: List[dict]


class ProviderInfo(BaseModel):
    """LLM 供应商信息。"""

    provider: str
    label: str = ""
    model: str = ""
    configured: bool = False
    base_url: Optional[str] = None


class FeedbackRequest(BaseModel):
    """用户对某条回答的评价。"""

    question: str = Field(..., description="对应的用户问题")
    rating: str = Field(..., description="up 表示有帮助，down 表示没帮助")
    answer: str = Field("", description="模型给出的回答原文")
    session_id: str = Field("", description="会话标识")
    sources: List[str] = Field(default_factory=list, description="本次引用的文档名")
    comment: str = Field("", description="可选补充说明")
