# -*- coding: utf-8 -*-
"""提前下载模型文件。

用法::

    python -m app.tools.prefetch_models              # 下载向量模型 + 重排模型
    python -m app.tools.prefetch_models --rerank-only
    python -m app.tools.prefetch_models --check      # 只检查是否已就绪

为什么单独做一个脚本：重排模型有 1GB 左右，让服务在后台悄悄拉不合适——
启动变慢、失败原因藏在日志里。放在这里可以看着进度跑，失败了重跑即可
（已下载的部分会自动续传）。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings


def _cache_dir(model_name: str) -> Path:
    import os

    hf_home = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
    return Path(hf_home) / "hub" / ("models--" + model_name.replace("/", "--"))


def is_downloaded(model_name: str) -> bool:
    """模型是否已经完整落在本地缓存里。"""
    configured = Path(model_name).expanduser()
    if configured.is_dir():
        return True
    snapshots = _cache_dir(model_name) / "snapshots"
    if not snapshots.is_dir():
        return False
    for snapshot in snapshots.iterdir():
        if not snapshot.is_dir():
            continue
        names = {p.name for p in snapshot.iterdir()}
        if {"config.json"} <= names and ({"model.safetensors"} & names or {"pytorch_model.bin"} & names):
            return True
    return False


def fetch(model_name: str, retries: int = 5) -> bool:
    """下载模型，失败自动重试（已下载部分会续传）。"""
    if Path(model_name).expanduser().is_dir():
        print("  = %s 是本地目录，无需下载" % model_name)
        return True

    from huggingface_hub import snapshot_download

    for attempt in range(1, retries + 1):
        started = time.perf_counter()
        try:
            snapshot_download(model_name)
            print(
                "  ✓ %s 完成（第 %d 次尝试，耗时 %.0fs）"
                % (model_name, attempt, time.perf_counter() - started)
            )
            return True
        except Exception as exc:
            print(
                "  ✗ %s 第 %d 次失败：%s"
                % (model_name, attempt, str(exc)[:160].replace("\n", " "))
            )
            if attempt < retries:
                time.sleep(3)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="预下载模型文件")
    parser.add_argument("--embed-only", action="store_true", help="只处理向量模型")
    parser.add_argument("--rerank-only", action="store_true", help="只处理重排模型")
    parser.add_argument("--check", action="store_true", help="只检查，不下载")
    args = parser.parse_args()

    settings = get_settings()
    targets = []
    if not args.rerank_only:
        targets.append(("向量模型", settings.retrieval.embedding.model_name))
    if not args.embed_only:
        targets.append(("重排模型", settings.retrieval.rerank.model_name))

    print("HF_ENDPOINT : %s" % (settings.retrieval.embedding.hf_endpoint or "(未设置)"))
    print("缓存目录    : %s" % _cache_dir("x").parent)
    print("")

    failed = []
    for label, model_name in targets:
        if is_downloaded(model_name):
            print("  = %s 已就绪：%s" % (label, model_name))
            continue
        if args.check:
            print("  ! %s 尚未下载：%s" % (label, model_name))
            failed.append(model_name)
            continue
        print("  ↓ 正在下载 %s：%s" % (label, model_name))
        if not fetch(model_name):
            failed.append(model_name)

    print("")
    if failed:
        print("以下模型未就绪，服务仍可运行（对应能力自动跳过）：")
        for name in failed:
            print("  - %s" % name)
        return 1
    print("全部模型就绪 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
