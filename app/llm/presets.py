# -*- coding: utf-8 -*-
"""
LLM 供应商预设
==============

每个预设描述「怎么连上一家模型服务」。绝大多数国产大模型都提供 OpenAI
兼容接口（/v1/chat/completions），因此这里只需描述 base_url / model /
API Key 环境变量名三件事。

新增一家供应商只需在此登记一条记录，无需改动任何业务代码。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class LLMPreset:
    """一家 LLM 供应商的连接描述。"""

    key: str
    label: str
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""
    openai_compatible: bool = True
    notes: str = ""

    @property
    def ready(self) -> bool:
        """预设本身是否已带齐连接信息（是否还需要用户补配置）。"""
        return bool(self.base_url and self.model)


# --------------------------------------------------------------------------
# 供应商登记表（base_url 指向 OpenAI 兼容根路径，不含 /chat/completions）
# --------------------------------------------------------------------------
PRESETS: Dict[str, LLMPreset] = {
    "deepseek": LLMPreset(
        key="deepseek",
        label="DeepSeek 深度求索",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        api_key_env="DEEPSEEK_API_KEY",
        notes="通用大模型，本项目历史默认供应商。",
    ),
    "shennong": LLMPreset(
        key="shennong",
        label="神农大模型（中国农业大学）",
        base_url="https://api.agent-tech.cc/api/v1",
        model="sn",
        api_key_env="SHENNONG_API_KEY",
        notes=(
            "农业垂直领域大模型（神农 4.0，中国农业大学信息与电气工程学院研发）。"
            "接口为 OpenAI 兼容，支持 SSE 流式输出；需要 SHENNONG_API_KEY。"
            "若对接方另有内网地址，用 SHENNONG_BASE_URL 覆盖即可。"
        ),
    ),
    "qwen": LLMPreset(
        key="qwen",
        label="通义千问（阿里云百炼）",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        api_key_env="DASHSCOPE_API_KEY",
    ),
    "zhipu": LLMPreset(
        key="zhipu",
        label="智谱 GLM",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-flash",
        api_key_env="ZHIPU_API_KEY",
    ),
    "moonshot": LLMPreset(
        key="moonshot",
        label="月之暗面 Kimi",
        base_url="https://api.moonshot.cn/v1",
        model="moonshot-v1-8k",
        api_key_env="MOONSHOT_API_KEY",
    ),
    "ollama": LLMPreset(
        key="ollama",
        label="本地 Ollama（离线部署）",
        base_url="http://127.0.0.1:11434/v1",
        model="qwen2.5:7b",
        api_key_env="OLLAMA_API_KEY",
        notes="本地推理，无需真实 API Key（占位填 ollama 即可），适合内网或离线场景。",
    ),
    "custom": LLMPreset(
        key="custom",
        label="自定义 OpenAI 兼容服务",
        base_url="",
        model="",
        api_key_env="LLM_API_KEY",
        notes="任何兼容 /v1/chat/completions 的服务，填 LLM_BASE_URL 与 LLM_MODEL 即可。",
    ),
}

DEFAULT_PROVIDER = "deepseek"


def get_preset(key: Optional[str]) -> LLMPreset:
    """按 key 取预设，未知 key 一律回落到自定义预设。"""
    if not key:
        return PRESETS[DEFAULT_PROVIDER]
    return PRESETS.get(key.strip().lower(), PRESETS["custom"])


def list_presets() -> list:
    """供 /api/providers 展示可选供应商。"""
    return [
        {
            "key": p.key,
            "label": p.label,
            "model": p.model,
            "base_url": p.base_url,
            "openai_compatible": p.openai_compatible,
            "needs_setup": not p.ready,
            "notes": p.notes,
        }
        for p in PRESETS.values()
    ]
