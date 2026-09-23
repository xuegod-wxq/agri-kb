# -*- coding: utf-8 -*-
"""页面路由。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """渲染前端聊天页面。"""
    return request.app.state.templates.TemplateResponse(
        request=request, name="index.html"
    )
