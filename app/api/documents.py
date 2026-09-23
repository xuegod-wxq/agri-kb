# -*- coding: utf-8 -*-
"""知识库文档相关接口。"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import get_repository, get_retriever, get_settings_dep
from app.config import Settings
from app.core.logging import get_logger
from app.ingest.loaders import ParseError, UnsupportedFormatError, extract_text
from app.ingest.repository import DocumentRepository
from app.retrieval.engine import HybridRetriever
from app.schemas import DocumentDetail, DocumentInfo, UploadResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["documents"])


@router.get("/documents", response_model=List[DocumentInfo])
async def list_documents(repository: DocumentRepository = Depends(get_repository)):
    """列出知识库与上传目录中的全部文档。"""
    return repository.list_documents()


@router.get("/document/{filename:path}", response_model=DocumentDetail)
async def get_document(
    filename: str,
    repository: DocumentRepository = Depends(get_repository),
):
    """读取单篇文档全文（仅纯文本格式可预览）。"""
    document = repository.read(filename)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在或不可预览")
    return document


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    repository: DocumentRepository = Depends(get_repository),
    retriever: HybridRetriever = Depends(get_retriever),
    settings: Settings = Depends(get_settings_dep),
):
    """
    上传文档（txt / md / pdf / docx / doc）。

    解析为纯文本后落盘，并重建检索索引。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="未提供文件名")

    raw = await file.read()
    limit = settings.max_upload_mb * 1024 * 1024
    if len(raw) > limit:
        raise HTTPException(
            status_code=400, detail=f"文件超过 {settings.max_upload_mb}MB 上限"
        )

    try:
        text = extract_text(file.filename, raw)
    except (UnsupportedFormatError, ParseError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    destination = repository.save_upload(file.filename, text)
    documents, chunks = retriever.rebuild(repository.load_for_index())
    logger.info("上传成功：%s（当前 %d 篇 / %d 片段）", destination.name, documents, chunks)
    return UploadResponse(filename=destination.name, docs=documents, chunks=chunks)


@router.delete("/document/{filename:path}")
async def delete_document(
    filename: str,
    repository: DocumentRepository = Depends(get_repository),
    retriever: HybridRetriever = Depends(get_retriever),
):
    """删除上传目录中的文档（知识库原始文档不允许删除）。"""
    if not repository.delete(filename):
        raise HTTPException(status_code=404, detail="文档不存在或不允许删除")
    documents, chunks = retriever.rebuild(repository.load_for_index())
    return {"status": "ok", "docs": documents, "chunks": chunks}
