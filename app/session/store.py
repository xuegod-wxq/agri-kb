# -*- coding: utf-8 -*-
"""
会话存储
========

抽象出 SessionStore 接口，并提供两种实现：

* JsonSessionStore   单文件 JSON，写入用「临时文件 + 原子替换」，简单可读；
* SqliteSessionStore SQLite（WAL 模式），只追加行，支持并发与事务回滚。

通过 .env 的 SESSION_BACKEND=json|sqlite 切换，业务代码无感。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Optional

from app.config import SessionSettings
from app.core.logging import get_logger

logger = get_logger(__name__)


class SessionStore(ABC):
    """对话历史存储接口。"""

    @abstractmethod
    def get(self, session_id: str) -> List[dict]:
        """取某个会话的全部消息，形如 [{'role': ..., 'content': ...}]。"""

    @abstractmethod
    def append(self, session_id: str, message: dict) -> None:
        """追加一条消息。"""

    @abstractmethod
    def reset(self, session_id: str) -> bool:
        """清空某个会话，返回该会话此前是否存在。"""

    @abstractmethod
    def count(self) -> int:
        """会话总数。"""

    def flush(self) -> None:
        """落盘；即时写入的实现无需动作。"""

    def close(self) -> None:
        """释放资源。"""


# ==========================================================================
# JSON 实现
# ==========================================================================

class JsonSessionStore(SessionStore):
    """单文件 JSON 存储。"""

    FORMAT_VERSION = 2

    def __init__(self, path, max_sessions: int = 100, legacy_path=None):
        self.path = Path(path)
        self.max_sessions = max_sessions
        self.legacy_path = Path(legacy_path) if legacy_path else None
        self._lock = threading.RLock()
        self._sessions: Dict[str, dict] = {}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    # ------------------------------------------------------------------ 读写

    def _load(self) -> None:
        source = None
        if self.path.exists():
            source = self.path
        elif self.legacy_path and self.legacy_path.exists():
            source = self.legacy_path
        if source is None:
            return

        try:
            payload = json.loads(source.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            logger.warning("会话文件解析失败，将从空历史开始：%s", exc)
            return

        if isinstance(payload, dict) and "sessions" in payload:
            raw = payload.get("sessions") or {}
        else:                                   # v1 旧格式：{sid: [msg, ...]}
            raw = payload if isinstance(payload, dict) else {}

        for session_id, value in raw.items():
            if isinstance(value, dict):
                messages = value.get("messages") or []
                updated_at = float(value.get("updated_at") or 0)
            else:
                messages = value or []
                updated_at = 0.0
            self._sessions[session_id] = {"updated_at": updated_at, "messages": messages}

        if source is self.legacy_path:
            logger.info("已从旧版 conversations.json 读取 %d 个会话", len(self._sessions))
            try:
                self._save()
            except Exception as exc:
                logger.warning("迁移会话数据失败：%s", exc)

    def _save(self) -> None:
        """原子写入：先写临时文件再替换，避免写一半崩溃损坏数据。"""
        payload = {"version": self.FORMAT_VERSION, "sessions": self._sessions}
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, self.path)

    def _prune(self) -> None:
        if self.max_sessions <= 0 or len(self._sessions) <= self.max_sessions:
            return
        ordered = sorted(
            self._sessions.items(),
            key=lambda kv: kv[1].get("updated_at", 0),
            reverse=True,
        )
        removed = len(self._sessions) - self.max_sessions
        self._sessions = dict(ordered[: self.max_sessions])
        logger.info("会话数超限，淘汰最旧的 %d 个会话", removed)

    # ------------------------------------------------------------------ 接口

    def get(self, session_id: str) -> List[dict]:
        with self._lock:
            entry = self._sessions.get(session_id)
            return [dict(m) for m in entry["messages"]] if entry else []

    def append(self, session_id: str, message: dict) -> None:
        with self._lock:
            entry = self._sessions.setdefault(session_id, {"updated_at": 0.0, "messages": []})
            entry["messages"].append(dict(message))
            entry["updated_at"] = time.time()
            self._prune()
            try:
                self._save()
            except Exception as exc:
                logger.warning("会话落盘失败（不影响本次回答）：%s", exc)

    def reset(self, session_id: str) -> bool:
        with self._lock:
            existed = session_id in self._sessions
            if existed:
                del self._sessions[session_id]
                try:
                    self._save()
                except Exception as exc:
                    logger.warning("会话落盘失败：%s", exc)
            return existed

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)


# ==========================================================================
# SQLite 实现
# ==========================================================================

class SqliteSessionStore(SessionStore):
    """SQLite 存储：只追加行，支持并发与事务。"""

    def __init__(self, path, max_sessions: int = 100):
        self.path = Path(path)
        self.max_sessions = max_sessions
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role       TEXT NOT NULL,
                    content    TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_messages_session
                    ON messages(session_id, id);
                """
            )

    def get(self, session_id: str) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def _prune(self) -> None:
        if self.max_sessions <= 0:
            return
        total = self._conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]
        if total <= self.max_sessions:
            return
        stale = self._conn.execute(
            "SELECT session_id FROM sessions ORDER BY updated_at DESC LIMIT -1 OFFSET ?",
            (self.max_sessions,),
        ).fetchall()
        for row in stale:
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (row["session_id"],))
            self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (row["session_id"],))
        if stale:
            logger.info("会话数超限，淘汰最旧的 %d 个会话", len(stale))

    def append(self, session_id: str, message: dict) -> None:
        now = time.time()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO messages(session_id, role, content, created_at) VALUES (?,?,?,?)",
                (session_id, message.get("role", ""), message.get("content", ""), now),
            )
            self._conn.execute(
                "INSERT INTO sessions(session_id, updated_at) VALUES (?,?) "
                "ON CONFLICT(session_id) DO UPDATE SET updated_at = excluded.updated_at",
                (session_id, now),
            )
            self._prune()

    def reset(self, session_id: str) -> bool:
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        return existing is not None

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()["c"]

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ==========================================================================
# 工厂
# ==========================================================================

def create_session_store(settings: SessionSettings) -> SessionStore:
    """按配置创建会话存储实现。"""
    backend = (settings.backend or "json").lower()
    if backend == "sqlite":
        logger.info("会话存储后端：SQLite（%s）", settings.sqlite_path)
        return SqliteSessionStore(settings.sqlite_path, settings.max_sessions)
    logger.info("会话存储后端：JSON（%s）", settings.json_path)
    return JsonSessionStore(
        settings.json_path,
        settings.max_sessions,
        legacy_path=settings.legacy_json_path,
    )
