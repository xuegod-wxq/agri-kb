# -*- coding: utf-8 -*-
"""供应商工厂。

根据配置实例化具体的 LLMProvider。新增非 OpenAI 兼容的供应商时，
在此登记一个分支即可，其余层无需改动。
"""
from __future__ import annotations

from app.config import LLMSettings
from app.core.logging import get_logger
from app.llm.base import LLMProvider
from app.llm.openai_compatible import OpenAICompatibleProvider
from app.llm.presets import get_preset

logger = get_logger(__name__)


def create_provider(settings: LLMSettings) -> LLMProvider:
    """按配置创建 LLM 供应商实例。"""
    preset = get_preset(settings.provider)

    if not preset.openai_compatible:
        raise NotImplementedError(
            f"供应商 {settings.provider} 暂不支持非 OpenAI 兼容协议"
        )

    provider = OpenAICompatibleProvider(
        base_url=settings.base_url,
        api_key=settings.api_key,
        model=settings.model,
        name=settings.provider,
        label=settings.label or preset.label,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout=settings.timeout,
        connect_timeout=settings.connect_timeout,
        max_retries=settings.max_retries,
        keepalive_expiry=settings.keepalive_expiry,
    )

    if provider.is_configured():
        logger.info(
            "LLM 供应商：%s（%s @ %s）", provider.label, provider.model, provider.base_url
        )
    else:
        logger.warning(
            "LLM 供应商 %s 尚未配置完整，缺少：%s",
            provider.label,
            "、".join(settings.missing),
        )
    return provider
