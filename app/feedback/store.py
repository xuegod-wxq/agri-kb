# -*- coding: utf-8 -*-
"""用户反馈存储（SQLite）。

反馈天然是「一张表 + 各种聚合查询」，所以直接用 SQLite，不套 JSON。
记录问题、回答、引用来源、模型与评分，便于：
  * 统计好评率；
  * 把点踩的案例捞出来，补进 tests/eval_set.json 当评测题。
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)

RATINGS = ("up", "down")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    session_id TEXT,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    sources    TEXT NOT NULL,
    rating     TEXT NOT NULL,
    comment    TEXT,
    provider   TEXT,
    model      TEXT
);
CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating, created_at DESC);
"""


class FeedbackStore:
    """反馈存储。enabled=False 时所有写操作静默丢弃。"""

    def __init__(self, path: Optional[Path] = None, enabled: bool = True) -> None:
        self.enabled = enabled
        self.path = Path(path) if path else None
        self._lock = threading.RLock()
        self._conn = None
        if not self.enabled or self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ 写入

    def add(
        self,
        question: str,
        answer: str,
        rating: str,
        sources: Optional[List[str]] = None,
        session_id: str = "",
        comment: str = "",
        provider: str = "",
        model: str = "",
    ) -> Optional[int]:
        """记录一条反馈，返回自增 id；未启用时返回 None。"""
        rating = (rating or "").strip().lower()
        if rating not in RATINGS:
            raise ValueError(f"评分只能是 {RATINGS}")
        if not self.enabled or self._conn is None:
            return None
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "INSERT INTO feedback(created_at, session_id, question, answer, sources,"
                " rating, comment, provider, model) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    time.time(),
                    session_id,
                    question,
                    answer,
                    json.dumps(sources or [], ensure_ascii=False),
                    rating,
                    comment,
                    provider,
                    model,
                ),
            )
        return cursor.lastrowid

    # ------------------------------------------------------------------ 查询

    def stats(self) -> Dict:
        """好评/差评统计。"""
        if self._conn is None:
            return {"enabled": False, "total": 0, "up": 0, "down": 0, "approval_rate": None}
        with self._lock:
            rows = self._conn.execute(
                "SELECT rating, COUNT(*) AS n FROM feedback GROUP BY rating"
            ).fetchall()
            total = sum(r["n"] for r in rows)
        counts = {r["rating"]: r["n"] for r in rows}
        up, down = counts.get("up", 0), counts.get("down", 0)
        return {
            "enabled": True,
            "total": total,
            "up": up,
            "down": down,
            "approval_rate": round(up / total, 3) if total else None,
        }

    def recent(self, limit: int = 20, rating: Optional[str] = None) -> List[Dict]:
        """最近的反馈明细；rating 传 'down' 可只看点踩的。"""
        if self._conn is None:
            return []
        sql = "SELECT * FROM feedback"
        params: list = []
        if rating:
            sql += " WHERE rating = ?"
            params.append(rating)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "session_id": row["session_id"],
                "question": row["question"],
                "answer": row["answer"],
                "sources": json.loads(row["sources"] or "[]"),
                "rating": row["rating"],
                "comment": row["comment"] or "",
                "provider": row["provider"] or "",
                "model": row["model"] or "",
            }
            for row in rows
        ]

    def close(self) -> None:
        if self._conn is not None:
            with self._lock:
                self._conn.close()
            self._conn = None
