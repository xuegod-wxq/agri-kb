# -*- coding: utf-8 -*-
"""OpenAI 兼容供应商实现。

国内绝大多数大模型服务（DeepSeek、通义千问、智谱、月之暗面、本地 vLLM /
Ollama 等）都提供 /v1/chat/completions 的 SSE 流式接口。只要 base_url 与
model 对得上，本类即可直接驱动，因此换供应商通常不需要写新代码。
"""
from __future__ import annotations

import json
import asyncio
from typing import AsyncIterator, Optional, Sequence

import httpx

from app.core.logging import get_logger
from app.llm.base import LLMError, LLMProvider

logger = get_logger(__name__)

# 网络异常的友好解释。注意顺序：子类必须放在父类前面，
# 例如 ConnectTimeout 属于 TimeoutException 而非 ConnectError。
_NETWORK_HINTS = (
    (httpx.ConnectTimeout, "连接超时：网络到不了模型服务"),
    (httpx.ReadTimeout, "读取超时：模型服务长时间没有返回数据"),
    (httpx.WriteTimeout, "发送请求超时"),
    (httpx.PoolTimeout, "连接池超时"),
    (httpx.ConnectError, "无法建立连接：DNS 解析失败、网络不通或被防火墙拦截"),
    (httpx.ReadError, "读取响应中断"),
    (httpx.RemoteProtocolError, "连接被服务端中途断开"),
    (httpx.ProxyError, "代理服务器错误"),
    (httpx.TimeoutException, "请求超时"),
    (httpx.TransportError, "网络传输错误"),
)

# 常见 HTTP 状态码的含义
_STATUS_HINTS = {
    400: "请求格式有误",
    401: "API Key 无效或已过期，请检查 .env 中的密钥",
    402: "账户余额不足",
    403: "没有访问权限",
    404: "接口地址或模型名不正确，请检查 base_url 与 model",
    422: "请求参数不被接受",
    429: "请求过于频繁，已被限流",
    500: "模型服务内部错误",
    502: "模型服务网关错误",
    503: "模型服务暂时不可用",
    504: "模型服务响应超时",
}


def describe_http_error(exc: Exception) -> str:
    """
    把 httpx 异常翻译成人能看懂的话。

    httpx 的超时类异常 str() 本身就是空字符串，直接拼进日志会得到
    「连接 deepseek 失败：」这种没有任何信息的提示，所以这里补上类型名
    和底层原因。
    """
    hint = next((text for cls, text in _NETWORK_HINTS if isinstance(exc, cls)), "网络错误")
    detail = str(exc).strip()
    if not detail:
        cause = exc.__cause__ or exc.__context__
        if cause is not None:
            detail = str(cause).strip() or type(cause).__name__
    if not detail:
        detail = type(exc).__name__
    return f"{hint}（{detail}）"


def _is_retryable(exc: Exception) -> bool:
    """瞬时网络故障才值得重试。"""
    return isinstance(exc, httpx.TransportError)


class OpenAICompatibleProvider(LLMProvider):
    """面向 OpenAI 兼容接口的通用 Provider。"""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        name: str = "openai-compatible",
        label: str = "",
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: float = 60.0,
        connect_timeout: float = 5.0,
        max_retries: int = 2,
        keepalive_expiry: float = 300.0,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.model = model or ""
        self.name = name
        self.label = label or name
        self.default_temperature = temperature
        self.default_max_tokens = max_tokens
        self.max_retries = max(0, int(max_retries))
        self._timeout = httpx.Timeout(timeout, connect=connect_timeout)
        # 长连接复用：跨会话保留 TCP 连接，避免每次提问都要重新握手，
        # 也就绕开了偶发的握手丢包（教育网线路尤其常见）。
        self._limits = httpx.Limits(
            max_connections=10,
            max_keepalive_connections=4,
            keepalive_expiry=keepalive_expiry,
        )
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------ 基础

    def is_configured(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    def describe(self) -> dict:
        info = super().describe()
        info["base_url"] = self.base_url
        return info

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout, limits=self._limits)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    # ------------------------------------------------------------------ 流式

    async def stream_chat(
        self,
        messages: Sequence[dict],
        temperature: float = None,
        max_tokens: int = None,
    ) -> AsyncIterator[str]:
        if not self.is_configured():
            raise LLMError(
                f"供应商 {self.name} 未配置完整：需要 base_url、model 与 api_key"
            )

        payload = {
            "model": self.model,
            "messages": list(messages),
            "stream": True,
            "temperature": self.default_temperature if temperature is None else temperature,
            "max_tokens": self.default_max_tokens if max_tokens is None else max_tokens,
        }

        for attempt in range(self.max_retries + 1):
            produced = False
            try:
                async for piece in self._stream_once(payload):
                    produced = True
                    yield piece
                return
            except LLMError as exc:
                # 已经吐出内容就无法重试，否则前端会看到重复片段
                if produced or not exc.retryable or attempt >= self.max_retries:
                    raise
                wait = 0.5 * (attempt + 1)
                logger.warning(
                    "模型调用失败（第 %d/%d 次尝试），%.1fs 后重试：%s",
                    attempt + 1, self.max_retries + 1, wait, exc,
                )
                await asyncio.sleep(wait)

    async def _stream_once(self, payload: dict) -> AsyncIterator[str]:
        """单次流式请求；失败时抛出带 retryable 标记的 LLMError。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        client = self._get_client()
        try:
            async with client.stream(
                "POST", self.endpoint, headers=headers, json=payload
            ) as response:
                if response.status_code != 200:
                    raw = await response.aread()
                    detail = raw.decode("utf-8", errors="ignore").strip()[:300]
                    hint = _STATUS_HINTS.get(response.status_code, "未知错误")
                    raise LLMError(
                        f"{self.label} 返回 {response.status_code}：{hint}。原始响应：{detail}",
                        retryable=response.status_code >= 500 or response.status_code == 429,
                    )

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content
        except httpx.HTTPError as exc:
            raise LLMError(
                f"连接 {self.label} 失败：{describe_http_error(exc)}",
                retryable=_is_retryable(exc),
            ) from exc
