# -*- coding: utf-8 -*-
"""端到端冒烟测试（无需 pytest，也不访问外网）。

运行方式::

    python tests/smoke_test.py

覆盖：文档接口、检索引擎、SSE 流式问答、会话持久化与恢复、健康检查。
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import asyncio
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import AsyncIterator, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.factory import create_app
from app.llm.base import LLMError, LLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider, describe_http_error

CHECKS = []


def check(name: str, condition: bool, detail: str = "") -> None:
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f"  <- {detail}" if detail else ""))
    CHECKS.append(bool(condition))
    if not condition:
        raise AssertionError(name)


class FakeProvider(LLMProvider):
    """替身模型：不联网，固定返回三段内容。"""

    name = "fake"
    label = "测试用替身模型"
    model = "fake-1"
    last_messages = []

    def is_configured(self) -> bool:
        return True

    async def stream_chat(
        self,
        messages: Sequence[dict],
        temperature: float = None,
        max_tokens: int = None,
    ) -> AsyncIterator[str]:
        self.last_messages = list(messages)
        for piece in ["棉花蕾期", "土壤含水量低于", "55% 时需灌溉。"]:
            yield piece


def parse_sse(raw: str) -> list:
    events = []
    for line in raw.splitlines():
        if not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload == "[DONE]":
            events.append({"type": "done"})
            continue
        events.append(json.loads(payload))
    return events


def run(client: TestClient, settings: Settings, tmp_dir: Path) -> None:
    # ---------- 1. 文档接口 ----------
    response = client.get("/api/documents")
    check("GET /api/documents 返回 200", response.status_code == 200)
    documents = response.json()
    check("文档列表非空", len(documents) > 0, f"{len(documents)} 篇")
    check("文档含 title/filename/size 字段",
          all({"title", "filename", "size"} <= set(d) for d in documents))
    check("标题已本地化为中文",
          any("\u4e00" <= ch <= "\u9fff" for ch in documents[0]["title"]),
          documents[0]["title"])

    first = documents[0]["filename"]
    response = client.get(f"/api/document/{first}")
    check("GET /api/document/{name} 返回 200", response.status_code == 200)
    check("文档正文非空", bool(response.json()["content"].strip()))
    check("不存在的文档返回 404",
          client.get("/api/document/__not_exist__.md").status_code == 404)
    check("目录穿越被拦截",
          client.get("/api/document/..%2F..%2Fmain.py").status_code == 404)

    # ---------- 2. 检索引擎 ----------
    retriever = client.app.state.retriever
    hits = retriever.search("棉花蕾期含水量低于多少需要灌溉")
    check("检索有命中", len(hits) > 0, f"{len(hits)} 条")
    check("检索结果按分数降序",
          all(hits[i].score >= hits[i + 1].score for i in range(len(hits) - 1)))
    counts = Counter(h.filename for h in hits)
    check("单篇文档贡献片段不超过上限",
          max(counts.values()) <= settings.retrieval.max_chunks_per_document
          or len(hits) < settings.retrieval.top_k,
          str(dict(counts)))
    irrelevant = retriever.search("量子计算机如何实现超导")
    check("相关问题得分高于无关问题",
          hits[0].score > (irrelevant[0].score if irrelevant else 0.0),
          f"{hits[0].score:.3f} vs "
          f"{(irrelevant[0].score if irrelevant else 0.0):.3f}")

    # ---------- 2b. 重排接线（替身模型，不需要真的下载 reranker）----------
    from app.retrieval.reranker import CrossEncoderReranker

    class FakeCrossEncoder:
        """片段越长分越高——只是为了让排序结果可预测。"""

        def predict(self, pairs, show_progress_bar=False):
            return [len(text) / 100.0 for _, text in pairs]

    original_reranker = retriever.reranker
    original_settings = retriever.settings
    # 引擎是按 settings.rerank.enabled 决定要不要重排的，两边都要改
    retriever.settings = replace(
        original_settings,
        rerank=replace(original_settings.rerank, enabled=True),
    )
    stub = CrossEncoderReranker(replace(settings.retrieval.rerank, enabled=True))
    stub._model = FakeCrossEncoder()
    retriever.reranker = stub
    try:
        reranked = retriever.search("棉花蕾期含水量", top_k=3)
        check("重排结果按 rerank 分数降序",
              all(reranked[i].score >= reranked[i + 1].score
                  for i in range(len(reranked) - 1)),
              str([round(h.score, 3) for h in reranked]))
        check("重排分数已写入命中对象",
              all(h.rerank_score > 0 for h in reranked))
        check("重排分数是 0~1 的概率值",
              all(0.0 < h.rerank_score < 1.0 for h in reranked))
    finally:
        retriever.reranker = original_reranker
        retriever.settings = original_settings

    # ---------- 3. 未配置供应商时的提示 ----------
    response = client.post("/api/chat/stream",
                           json={"message": "你好", "session_id": "s0"})
    check("未配置模型时仍返回 200", response.status_code == 200)
    events = parse_sse(response.text)
    check("未配置模型时给出明确提示",
          any(e["type"] == "error" and "大模型尚未配置" in e["data"] for e in events))

    # ---------- 4. 流式问答（注入替身模型） ----------
    fake = FakeProvider()
    client.app.state.llm = fake
    session_id = "sess_test_001"
    with client.stream("POST", "/api/chat/stream",
                       json={"message": "棉花蕾期什么时候灌溉？",
                             "session_id": session_id}) as streamed:
        body = "".join(streamed.iter_text())

    events = parse_sse(body)
    kinds = [e["type"] for e in events]
    check("SSE 事件顺序为 sources -> chunk -> done",
          kinds[0] == "sources" and kinds[-1] == "done", str(kinds))
    answer = "".join(e["data"] for e in events if e["type"] == "chunk")
    check("拼接后的回答完整",
          answer == "棉花蕾期土壤含水量低于55% 时需灌溉。", answer)
    sources = next(e["data"] for e in events if e["type"] == "sources")
    known = {d["filename"] for d in documents}
    check("sources 仅含已存在的文档",
          all(s["filename"] in known for s in sources))

    check("system 提示词在位", fake.last_messages[0]["role"] == "system")
    check("参考资料已注入用户消息", "参考资料" in fake.last_messages[-1]["content"])
    check("参考资料带中文标题（便于模型正确引用）",
          any(d["title"] in fake.last_messages[-1]["content"] for d in documents),
          fake.last_messages[-1]["content"][:60].replace("\n", " "))
    check("参考资料不暴露文件名（避免模型照抄）",
          ".md" not in fake.last_messages[-1]["content"].split("参考资料：")[-1],
          fake.last_messages[-1]["content"][:80].replace("\n", " "))

    # ---------- 5. 会话持久化 ----------
    history = client.get(f"/api/session/{session_id}").json()["messages"]
    check("会话记录了 user + assistant 两条", len(history) == 2, str(len(history)))
    check("assistant 内容已落库", history[1]["content"] == answer)

    stored = json.loads((tmp_dir / "conversations.json").read_text(encoding="utf-8"))
    check("JSON 会话文件已写入", session_id in stored.get("sessions", {}))

    # 用同一份数据重新建一个应用实例，模拟服务重启
    with TestClient(create_app(settings)) as restarted:
        restored = restarted.get(f"/api/session/{session_id}").json()["messages"]
    check("重启后会话历史可恢复", len(restored) == 2, str(len(restored)))
    check("恢复的内容与写入一致", restored[1]["content"] == answer)

    # ---------- 6. 会话重置 ----------
    reset = client.post("/api/session/reset",
                        json={"session_id": session_id}).json()
    check("重置返回 cleared=True", reset["cleared"] is True)
    check("重置后历史为空",
          client.get(f"/api/session/{session_id}").json()["messages"] == [])

    # ---------- 7. 健康检查与页面 ----------
    health = client.get("/health").json()
    check("健康检查 status=ok", health["status"] == "ok")
    check("健康检查暴露片段数", health["chunks"] > 0, str(health["chunks"]))
    check("GET / 返回 200", client.get("/").status_code == 200)
    check("静态资源可访问", client.get("/static/js/app.js").status_code == 200)

    # ---------- 8. 反馈闭环 ----------
    up = client.post("/api/feedback", json={
        "question": "棉花蕾期什么时候灌溉？",
        "answer": answer,
        "rating": "up",
        "sources": [s["filename"] for s in sources],
        "session_id": "sess_test_001",
    })
    check("提交好评返回 200", up.status_code == 200, up.text[:80])
    check("好评返回自增 id", isinstance(up.json().get("id"), int), up.text[:80])

    down = client.post("/api/feedback", json={
        "question": "棉花蕾期什么时候灌溉？",
        "answer": answer,
        "rating": "down",
        "comment": "答非所问",
    })
    check("提交差评返回 200", down.status_code == 200)

    bad = client.post("/api/feedback", json={"question": "x", "rating": "maybe"})
    check("非法评分返回 400", bad.status_code == 400)

    stats = client.get("/api/feedback/stats").json()
    check("反馈统计正确", stats["total"] == 2 and stats["up"] == 1 and stats["down"] == 1,
          str(stats))
    check("好评率计算正确", stats["approval_rate"] == 0.5, str(stats.get("approval_rate")))

    recent = client.get("/api/feedback/recent", params={"rating": "down"}).json()["items"]
    check("可按差评筛选复盘", len(recent) == 1 and recent[0]["comment"] == "答非所问",
          str(len(recent)))
    check("差评保留了引用来源字段", "sources" in recent[0])


def check_llm_error_handling() -> None:
    """网络异常提示与自动重试。"""
    # httpx 的超时异常 str() 为空，必须翻译成人能看懂的话
    message = describe_http_error(httpx.ConnectTimeout(""))
    check("超时异常不再是空提示",
          "连接超时" in message and message.strip().endswith("）"), message)

    # 链式异常要能挖出底层原因（例如 Windows 的 10060）
    try:
        try:
            raise OSError(10060, "connect timed out")
        except OSError as root:
            raise httpx.ConnectTimeout("") from root
    except httpx.ConnectTimeout as exc:
        chained = describe_http_error(exc)
    check("能显示底层原因", "10060" in chained, chained)

    # 瞬时故障只重试一次，且不会重复输出已生成的内容
    class FlakyProvider(OpenAICompatibleProvider):
        def __init__(self) -> None:
            super().__init__(base_url="http://127.0.0.1:1/v1", api_key="k",
                             model="m", name="flaky", label="Flaky", max_retries=1)
            self.calls = 0

        async def _stream_once(self, payload) -> AsyncIterator[str]:
            self.calls += 1
            if self.calls == 1:
                raise LLMError("连接超时", retryable=True)
            yield "重试成功"

    async def collect(provider) -> list:
        return [piece async for piece in provider.stream_chat(
            [{"role": "user", "content": "hi"}])]

    provider = FlakyProvider()
    pieces = asyncio.run(collect(provider))
    check("瞬时故障自动重试", pieces == ["重试成功"] and provider.calls == 2,
          f"{pieces} calls={provider.calls}")

    # 鉴权类错误不该重试
    class AuthFailProvider(OpenAICompatibleProvider):
        def __init__(self) -> None:
            super().__init__(base_url="http://127.0.0.1:1/v1", api_key="k",
                             model="m", name="auth", label="Auth", max_retries=1)
            self.calls = 0

        async def _stream_once(self, payload) -> AsyncIterator[str]:
            self.calls += 1
            raise LLMError("401 未授权", retryable=False)
            yield  # pragma: no cover

    auth = AuthFailProvider()
    try:
        asyncio.run(collect(auth))
        raised = False
    except LLMError:
        raised = True
    check("鉴权失败不重试", raised and auth.calls == 1, f"calls={auth.calls}")


def main() -> int:
    tmp_dir = Path(tempfile.mkdtemp(prefix="agri-kb-test-"))
    try:
        settings = Settings.load(environ={
            "DATA_DIR": str(tmp_dir),
            "SESSION_JSON_PATH": str(tmp_dir / "conversations.json"),
            "EMBED_ENABLED": "false",
            "EMBED_WARMUP": "false",
            "LLM_PROVIDER": "custom",
            "LLM_API_KEY": "",
            "LLM_BASE_URL": "",
            "LLM_MODEL": "",
        })
        with TestClient(create_app(settings)) as client:
            run(client, settings, tmp_dir)

        check_llm_error_handling()

        print(f"\n全部 {len(CHECKS)} 项检查通过 ✅")
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
