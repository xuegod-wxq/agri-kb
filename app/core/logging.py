# -*- coding: utf-8 -*-
"""日志初始化。"""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(level: str = "info") -> None:
    """初始化根日志配置，重复调用不会重复添加 handler。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
