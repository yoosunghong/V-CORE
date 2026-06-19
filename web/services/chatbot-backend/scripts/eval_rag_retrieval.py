"""PA.4 RAG regression runner over the live Qdrant knowledge store.

Example:
    python scripts/eval_rag_retrieval.py --qdrant-url http://127.0.0.1:6333 \
        --embed-base-url http://127.0.0.1:11434 --top-k 5 --fetch-k 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.benchmarks.rag_cases import (  # noqa: E402
    GRAPH_RAG_BASELINE_RANKINGS,
    GRAPH_RAG_RETRIEVAL_CASES,
    RAG_ANSWER_CASES,
    RAG_RETRIEVAL_CASES,
)
from app.benchmarks.rag_eval import evaluate_answer_grounding, evaluate_rankings  # noqa: E402
from app.infrastructure.knowledge_gateway import QdrantKnowledgeGateway  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate PA.4 RAG retrieval and grounding quality.")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--collection", default="vcore_operations_ko")
    parser.add_argument("--embed-base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--embed-model", default="bge-m3")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--fetch-k", type=int, default=10)
    parser.add_argument("--rerank-mode", default="lexical", choices=("vector", "lexical", "llm"))
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--rerank-base-url", default="")
    parser.add_argument("--rerank-model", default="")
    parser.add_argument("--baseline", default="")
    parser.add_argument("--out", default="")
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    gateway = QdrantKnowledgeGateway(
        qdrant_url=args.qdrant_url,
        collection=args.collection,
        embed_base_url=args.embed_base_url,
        embed_model=args.embed_model,
        fetch_k=args.fetch_k,
        rerank_mode=args.rerank_mode,
        min_score=args.min_score,
        rerank_base_url=args.rerank_base_url or None,
        rerank_model=args.rerank_model or None,
    )
    rankings: dict[str, tuple[str, ...]] = {}
    details: dict[str, list[dict[str, object]]] = {}
    for case in RAG_RETRIEVAL_CASES:
        chunks = await gateway.retrieve(case.query, "rag-eval", top_k=args.top_k)
        rankings[case.query] = tuple(chunk.document_id for chunk in chunks)
        details[case.query] = [
            {
                "document_id": chunk.document_id,
                "title": chunk.title,
                "score": chunk.score,
                "vector_score": chunk.vector_score,
                "rerank_score": chunk.rerank_score,
            }
            for chunk in chunks
        ]
    retrieval_rows, retrieval_summary = evaluate_rankings(
        RAG_RETRIEVAL_CASES, rankings, args.top_k
    )
    graph_rows, graph_summary = evaluate_rankings(
        GRAPH_RAG_RETRIEVAL_CASES, GRAPH_RAG_BASELINE_RANKINGS, 3
    )
    answer_rows, answer_summary = evaluate_answer_grounding(RAG_ANSWER_CASES)
    result = {
        "settings": vars(args),
        "summary": {
            "retrieval": retrieval_summary,
            "graph_retrieval": graph_summary,
            "answer_grounding": answer_summary,
        },
        "rows": {
            "retrieval": [asdict(row) for row in retrieval_rows],
            "graph_retrieval": [asdict(row) for row in graph_rows],
            "answer_grounding": [asdict(row) for row in answer_rows],
        },
        "details": details,
    }
    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        result["baseline_check"] = _check_baseline(result["summary"], baseline)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


def _check_baseline(
    summary: dict[str, dict[str, float]],
    baseline: dict[str, object],
) -> dict[str, object]:
    thresholds = baseline.get("thresholds", {})
    checks: dict[str, bool] = {}
    for metric_path, threshold in thresholds.items():
        section, metric = metric_path.split(".", maxsplit=1)
        value = summary.get(section, {}).get(metric, 0.0)
        checks[metric_path] = value >= float(threshold)
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "thresholds": thresholds,
    }


if __name__ == "__main__":
    asyncio.run(main())
