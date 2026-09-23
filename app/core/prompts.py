# -*- coding: utf-8 -*-
"""
提示词模板
==========

集中管理送入大模型的系统提示词与上下文拼装逻辑，方便单独调优而不用改业务代码。
"""
from __future__ import annotations

from typing import Iterable, Sequence

# 系统提示词：约束模型的角色、知识来源优先级与输出格式
SYSTEM_PROMPT = """你是新疆地区的农业技术专家，为种植户和农技人员提供解答。

回答要求：
1. 优先依据「参考资料」作答，资料中的数值指标（含水量、用量、温度阈值、药剂浓度等）必须原样引用，不得改写或估算。
2. 资料未覆盖的部分，可用通用农业知识补充，但必须在相应内容后标注「（通用）」。
3. 资料与通用知识冲突时，以资料为准。
4. 引用资料时在句末标注来源，格式：【来源：文档标题】。
   文档标题就是参考资料中方括号书名号里的名称，只写名称本身，
   不要附加文件名、编号或其它说明。
5. 使用 Markdown 排版：要点用列表，操作步骤用有序列表，数值指标可用表格。
6. 资料不足且无通用知识可依据时，直接说明「知识库中暂无相关内容」，不要编造。
7. 用简洁的简体中文作答，避免空话套话。"""


def build_context(results: Iterable, titles: dict = None) -> str:
    """
    把检索结果拼成「参考资料」文本块。

    results: 检索命中列表，元素需具备 filename / text 属性。
    titles:  {文件名: 中文标题} 映射。带上标题后，模型引用时会写
             【来源：棉花全生育期管理】而不是 【来源：cotton_full_cycle.md】。
    """
    titles = titles or {}
    parts = []
    for i, hit in enumerate(results, 1):
        filename = getattr(hit, "filename", "") or ""
        title = titles.get(filename) or filename
        text = getattr(hit, "text", "") or getattr(hit, "chunk", "")
        # 只把标题给模型：文件名对作答没有帮助，反而容易被照抄进引用里
        parts.append(f"[{i}] 《{title}》\n{text}")
    return "\n\n".join(parts)


def build_user_content(question: str, context: str) -> str:
    """把用户问题与参考资料组合成最终的用户消息。"""
    question = (question or "").strip()
    if not context:
        return f"问题：{question}\n\n（本次未检索到相关资料，请按通用知识作答并标注）"
    return f"问题：{question}\n\n参考资料：\n{context}"


def build_messages(
    question: str,
    context: str,
    history: Sequence[dict],
    history_window: int = 10,
) -> list:
    """
    组装发送给 LLM 的消息列表。

    结构：system 提示词 + 最近若干轮历史 + 本轮（问题 + 参考资料）
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history_window > 0 and history:
        messages.extend(dict(m) for m in history[-history_window:])
    messages.append({"role": "user", "content": build_user_content(question, context)})
    return messages
