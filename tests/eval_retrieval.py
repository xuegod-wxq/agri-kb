# -*- coding: utf-8 -*-
"""检索评测工具。

用法::

    python tests/eval_retrieval.py                 # 用当前 .env 的配置评测
    python tests/eval_retrieval.py --top-k 3       # 换成 recall@3
    python tests/eval_retrieval.py --no-embed      # 关掉向量，只看 BM25
    python tests/eval_retrieval.py --no-rerank     # 关掉重排
    python tests/eval_retrieval.py --json out.json # 结果落盘，便于前后对比
    python tests/eval_retrieval.py --min-recall 0.9  # 低于阈值则退出码非 0

评测题在 tests/eval_set.json，直接加题即可，不需要改代码。
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.ingest.repository import DocumentRepository
from app.retrieval.engine import HybridRetriever

EVAL_SET = Path(__file__).resolve().parent / "eval_set.json"


def load_cases(path: Path = EVAL_SET) -> List[dict]:
    """读取评测题。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("cases", [])


def run_eval(retriever: HybridRetriever, cases: List[dict], top_k: int = 5) -> Dict:
    """跑一遍评测，返回指标与逐题明细。"""
    details = []
    for case in cases:
        expected = case.get("expected") or []
        hits = retriever.search(case["question"], top_k=top_k)
        names = [h.filename for h in hits]
        rank = next(
            (i + 1 for i, name in enumerate(names) if name in expected),
            None,
        )
        details.append(
            {
                "question": case["question"],
                "category": case.get("category", "direct"),
                "expected": expected,
                "retrieved": names,
                "rank": rank,
                "hit": rank is not None,
                "scores": [round(h.score, 4) for h in hits],
            }
        )

    def metrics(rows: List[dict]) -> Dict:
        if not rows:
            return {"count": 0, "recall": 0.0, "mrr": 0.0}
        hit = sum(1 for r in rows if r["hit"])
        mrr = sum(1.0 / r["rank"] for r in rows if r["rank"]) / len(rows)
        return {
            "count": len(rows),
            "hit": hit,
            "recall": hit / len(rows),
            "mrr": mrr,
        }

    by_category = {}
    for category in sorted({d["category"] for d in details}):
        by_category[category] = metrics([d for d in details if d["category"] == category])

    retrieved_docs = {name for d in details for name in d["retrieved"]}
    return {
        "top_k": top_k,
        "overall": metrics(details),
        "by_category": by_category,
        "details": details,
        "retrieved_documents": sorted(retrieved_docs),
    }


def format_report(report: Dict, verbose: bool = False) -> str:
    lines = []
    overall = report["overall"]
    lines.append(
        "recall@%d = %d/%d = %.0f%%     MRR = %.3f"
        % (
            report["top_k"],
            overall["hit"],
            overall["count"],
            100 * overall["recall"],
            overall["mrr"],
        )
    )
    lines.append("")
    for category, m in report["by_category"].items():
        lines.append(
            "  %-12s %d/%d = %3.0f%%   MRR = %.3f"
            % (category, m["hit"], m["count"], 100 * m["recall"], m["mrr"])
        )

    misses = [d for d in report["details"] if not d["hit"]]
    if misses:
        lines.append("")
        lines.append("未命中 %d 题：" % len(misses))
        for d in misses:
            lines.append("  [%s] %s" % (d["category"], d["question"]))
            lines.append("    期望: %s" % ", ".join(d["expected"]))
            lines.append("    实际: %s" % ", ".join(d["retrieved"]))

    if verbose:
        lines.append("")
        lines.append("逐题明细：")
        for d in report["details"]:
            flag = "命中" if d["hit"] else "未中"
            rank = "第%d位" % d["rank"] if d["rank"] else "-"
            lines.append("  [%s] %-28s %s %s" % (flag, rank, d["question"][:26], ""))

    return "\n".join(lines)


def build_retriever(args) -> HybridRetriever:
    """按命令行开关构造检索器。"""
    settings = get_settings()
    retrieval = settings.retrieval

    embedding = retrieval.embedding
    if args.no_embed:
        embedding = replace(embedding, enabled=False, warmup=False)
    retrieval = replace(retrieval, embedding=embedding)

    rerank = getattr(retrieval, "rerank", None)
    if rerank is not None:
        enabled = rerank.enabled and not args.no_rerank
        retrieval = replace(retrieval, rerank=replace(rerank, enabled=enabled))

    retriever = HybridRetriever(retrieval, data_dir=settings.data_dir)
    repository = DocumentRepository(settings.knowledge_base_dir, settings.upload_dir)
    retriever.rebuild(repository.load_for_index())
    if not args.no_embed:
        retriever.warm()
    return retriever


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="检索评测")
    parser.add_argument("--top-k", type=int, default=5, help="取前 k 条计算 recall")
    parser.add_argument("--no-embed", action="store_true", help="关闭向量检索")
    parser.add_argument("--no-rerank", action="store_true", help="关闭重排")
    parser.add_argument("--verbose", action="store_true", help="打印逐题明细")
    parser.add_argument("--json", type=str, default="", help="把结果写入 JSON 文件")
    parser.add_argument("--min-recall", type=float, default=0.0, help="低于该值则退出码非 0")
    args = parser.parse_args(argv)

    cases = load_cases()
    if not cases:
        print("评测集为空，请检查 tests/eval_set.json")
        return 1

    retriever = build_retriever(args)
    report = run_eval(retriever, cases, top_k=args.top_k)

    print(format_report(report, verbose=args.verbose))

    if args.json:
        Path(args.json).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print("\n结果已写入 %s" % args.json)

    if report["overall"]["recall"] < args.min_recall:
        print(
            "\nrecall %.2f 低于阈值 %.2f" % (report["overall"]["recall"], args.min_recall)
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
