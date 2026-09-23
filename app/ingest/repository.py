# -*- coding: utf-8 -*-
"""
文档仓库
========

统一负责「知识库目录 + 上传目录」中文档的枚举、读取与写入。
上层（API / 检索）只面对文件名字符串，不关心物理路径。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

from app.ingest.loaders import SUPPORTED_SUFFIXES

_SAFE_NAME = re.compile(r"[^\w\u4e00-\u9fff.\-]+")
_PREVIEW_SUFFIXES = {".txt", ".md", ".markdown"}


class DocumentRepository:
    """管理知识库与上传目录内的文档。"""

    def __init__(self, knowledge_base_dir, upload_dir) -> None:
        self.knowledge_base_dir = Path(knowledge_base_dir)
        self.upload_dir = Path(upload_dir)
        self.knowledge_base_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ 枚举

    @property
    def search_dirs(self) -> List[Path]:
        """检索顺序：知识库优先，其次上传目录。"""
        return [self.knowledge_base_dir, self.upload_dir]

    def iter_files(self, suffixes=None) -> List[Path]:
        allowed = suffixes or SUPPORTED_SUFFIXES
        files: List[Path] = []
        for directory in self.search_dirs:
            if not directory.exists():
                continue
            files.extend(
                f for f in sorted(directory.iterdir())
                if f.is_file() and f.suffix.lower() in allowed
            )
        return files

    # ------------------------------------------------------------------ 元信息

    @staticmethod
    def extract_title(path: Path) -> str:
        """取 Markdown 一级标题；没有则用文件名兜底。"""
        if path.suffix.lower() in _PREVIEW_SUFFIXES:
            try:
                for line in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
                    line = line.strip()
                    if line.startswith("# ") and len(line) > 2:
                        return line[2:].strip()
                    if line:
                        break       # 首个非空行不是标题就不再往下找，避免命中正文里的 #
            except OSError:
                pass
        return path.stem.replace("_", " ")

    def list_documents(self) -> List[Dict]:
        """列出全部文档的摘要信息（供左侧知识库列表使用）。"""
        documents = []
        for path in self.iter_files():
            source = "knowledge_base" if path.parent == self.knowledge_base_dir else "uploads"
            documents.append(
                {
                    "title": self.extract_title(path),
                    "filename": path.name,
                    "size": path.stat().st_size,
                    "source": source,
                }
            )
        return documents

    # ------------------------------------------------------------------ 读取

    def resolve(self, filename: str) -> Optional[Path]:
        """
        把文件名解析为真实路径（防目录穿越）。

        只接受纯文件名，且必须落在受管目录内。
        """
        name = Path(filename or "").name
        if not name:
            return None
        for directory in self.search_dirs:
            root = directory.resolve()
            candidate = (directory / name).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.is_file():
                return candidate
        return None

    def read(self, filename: str) -> Optional[Dict]:
        """读取单篇文档（仅纯文本格式可预览）。"""
        path = self.resolve(filename)
        if path is None or path.suffix.lower() not in _PREVIEW_SUFFIXES:
            return None
        return {
            "name": self.extract_title(path),
            "filename": path.name,
            "content": path.read_text(encoding="utf-8-sig", errors="ignore"),
        }

    def load_for_index(self) -> List[Dict]:
        """加载全部可索引文档，供检索引擎重建索引。"""
        documents = []
        for path in self.iter_files(_PREVIEW_SUFFIXES):
            try:
                text = path.read_text(encoding="utf-8-sig", errors="ignore")
            except OSError:
                continue
            if text.strip():
                documents.append({"filename": path.name, "text": text})
        return documents

    # ------------------------------------------------------------------ 写入

    def save_upload(self, filename: str, text: str) -> Path:
        """保存上传解析后的文本，重名自动加序号。"""
        safe_name = _SAFE_NAME.sub("_", Path(filename or "").name).strip("._") or "document"
        suffix = Path(safe_name).suffix.lower()
        if suffix not in _PREVIEW_SUFFIXES:
            suffix = ".txt"
        stem = Path(safe_name).stem or "document"

        dest = self.upload_dir / f"{stem}{suffix}"
        counter = 1
        while dest.exists():
            dest = self.upload_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        dest.write_text(text, encoding="utf-8")
        return dest

    def delete(self, filename: str) -> bool:
        """删除上传目录中的文档（知识库原文不通过接口删除）。"""
        name = Path(filename or "").name
        root = self.upload_dir.resolve()
        target = (self.upload_dir / name).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return False
        if target.is_file():
            target.unlink()
            return True
        return False
