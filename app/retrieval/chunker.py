# -*- coding: utf-8 -*-
"""文本分块器。"""
from __future__ import annotations

import re
from typing import List

# 在句末标点之后切分，并保留标点本身（lookbehind 不消耗字符）
_SENTENCE_SPLIT = re.compile(r"(?<=[。；])")


def _merge_short(pieces: List[str], min_size: int, max_size: int) -> List[str]:
    """
    合并过短的片段。

    过短片段（比如只有 20 来字的一条列表项）词太少，BM25 和向量都给不出
    稳定分数，检索时容易被随机顶上来。这里把它们并入相邻片段：
    优先并进「前一块」，因为前面通常正是它所属的标题或上下文。
    """
    if min_size <= 0 or not pieces:
        return pieces

    merged: List[str] = []
    for piece in pieces:
        # 只有并入后仍在 max_size 以内才合并，否则一长串短列表项会滚成一个巨块
        if (
            merged
            and len(piece) < min_size
            and len(merged[-1]) + len(piece) + 1 <= max_size
        ):
            merged[-1] = merged[-1] + "\n" + piece
        else:
            merged.append(piece)

    # 首块过短时没有「前一块」可并，改为并入后一块
    if (
        len(merged) > 1
        and len(merged[0]) < min_size
        and len(merged[0]) + len(merged[1]) + 1 <= max_size
    ):
        merged[1] = merged[0] + "\n" + merged[1]
        merged.pop(0)
    return merged


def chunk_text(text: str, size: int = 400, min_size: int = 80) -> List[str]:
    """
    把长文档切成约 size 字的片段。

    步骤：
      1. 按换行分段，保持段落完整；
      2. 段落超长时按句号/分号切开，再重新累积到接近 size；
      3. 短段落向后累积，直到接近 size；
      4. 不足 min_size 的碎片并入相邻片段。
    """
    chunks: List[str] = []
    buf = ""

    for para in (text or "").split("\n"):
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) <= size:
            buf = f"{buf}\n{para}" if buf else para
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(para) > size:
            # 逐句累积，而不是每句单独成块
            for sentence in _SENTENCE_SPLIT.split(para):
                sentence = sentence.strip()
                if not sentence:
                    continue
                if len(buf) + len(sentence) <= size:
                    buf += sentence
                else:
                    if buf:
                        chunks.append(buf)
                    buf = sentence
        else:
            buf = para

    if buf:
        chunks.append(buf)
    return _merge_short(chunks, min_size, max_size=int(size * 1.2))
