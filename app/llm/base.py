# -*- coding: utf-8 -*-
"""LLM 供应商抽象。

业务层只依赖本模块的 LLMProvider 接口，不关心背后是 DeepSeek、
神农大模型还是本地 Ollama。换供应商 = 换一个实现类或改一段配置。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, List, Sequence


class LLMError(RuntimeError):
    """LLM 调用失败（网络异常、鉴权失败、返回非 200 等）。

    retryable 为 True 表示属于瞬时故障（超时、连接中断），
    在还没吐出任何内容前可以安全重试。
    """

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMProvider(ABC):
    """大模型供应商接口。"""

    name: str = "unknown"
    label: str = ""
    model: str = ""

    def is_configured(self) -> bool:
        """连接信息是否齐备。"""
        return True

    def describe(self) -> Dict:
        """供 /health、/api/providers 展示的元信息。"""
        return {
            "provider": self.name,
            "label": self.label,
            "model": self.model,
            "configured": self.is_configured(),
        }

    @abstractmethod
    def stream_chat(
        self,
        messages: Sequence[dict],
        temperature: float = None,
        max_tokens: int = None,
    ) -> AsyncIterator[str]:
        """以异步迭代器方式返回模型的增量输出。

        实现方遇到任何错误时应抛出 LLMError。
        """

    async def aclose(self) -> None:
        """释放底层连接资源。"""


def chunk_text_stream(text: str, size: int = 24) -> List[str]:
    """把整段文本切成小块（用于非流式实现的兜底）。"""
    if not text:
        return []
    return [text[i:i + size] for i in range(0, len(text), size)]
