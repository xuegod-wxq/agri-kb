# -*- coding: utf-8 -*-
"""中文分词器。"""
from __future__ import annotations

from typing import List

# CJK 字符区间：扩展 A 区、基本区、兼容表意文字
CJK_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF))


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in CJK_RANGES)


class ChineseTokenizer:
    """
    面向 BM25 的轻量分词器。

    策略：
      * 汉字 -> 逐字切分（无需词典，对农业专业术语更稳）
      * 英文/数字/下划线与连字符 -> 连续片段作为一个词，统一转小写
      * 其余符号 -> 视为分隔符
    """

    def tokenize(self, text: str) -> List[str]:
        tokens: List[str] = []
        buf: List[str] = []

        def flush() -> None:
            if buf:
                tokens.append("".join(buf).lower())
                buf.clear()

        for ch in text or "":
            if _is_cjk(ch):
                flush()
                tokens.append(ch)
            elif ch.isalnum() or ch in "-_":
                buf.append(ch)
            else:
                flush()
        flush()
        return tokens
