"""PA.3 retrieval-quality runner over the live Qdrant knowledge store.

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

from app.benchmarks.rag_cases import RAG_RETRIEVAL_CASES  # noqa: E402
from app.benchmarks.rag_eval import evaluate_rankings  # noqa: E402
from app.infrastructure.knowledge_gateway import QdrantKnowledgeGateway  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate PA.3 RAG retrieval quality.")
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
    rows, summary = evaluate_rankings(RAG_RETRIEVAL_CASES, rankings, args.top_k)
    result = {
        "settings": vars(args),
        "summary": summary,
        "rows": [asdict(row) for row in rows],
        "details": details,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    asyncio.run(main())
