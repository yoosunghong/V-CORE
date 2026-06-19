from __future__ import annotations

import math
from dataclasses import dataclass

from app.benchmarks.rag_cases import RagRetrievalCase


@dataclass(frozen=True)
class RagEvalRow:
    query: str
    category: str
    relevant_document_ids: tuple[str, ...]
    returned_document_ids: tuple[str, ...]
    recall_at_k: float
    ndcg_at_k: float


def recall_at_k(returned: list[str] | tuple[str, ...], relevant: set[str], k: int) -> float:
    if not relevant:
        return 1.0
    retrieved = set(returned[:k])
    return len(retrieved & relevant) / len(relevant)


def ndcg_at_k(returned: list[str] | tuple[str, ...], relevant: set[str], k: int) -> float:
    if not relevant:
        return 1.0
    dcg = 0.0
    for rank, document_id in enumerate(returned[:k], start=1):
        if document_id in relevant:
            dcg += 1.0 / math.log2(rank + 1)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def evaluate_rankings(
    cases: list[RagRetrievalCase] | tuple[RagRetrievalCase, ...],
    rankings: dict[str, list[str] | tuple[str, ...]],
    k: int,
) -> tuple[list[RagEvalRow], dict[str, float]]:
    rows: list[RagEvalRow] = []
    for case in cases:
        returned = tuple(rankings.get(case.query, ()))
        relevant = set(case.relevant_document_ids)
        rows.append(
            RagEvalRow(
                query=case.query,
                category=case.category,
                relevant_document_ids=case.relevant_document_ids,
                returned_document_ids=returned[:k],
                recall_at_k=recall_at_k(returned, relevant, k),
                ndcg_at_k=ndcg_at_k(returned, relevant, k),
            )
        )
    if not rows:
        return rows, {"recall_at_k": 0.0, "ndcg_at_k": 0.0}
    return rows, {
        "recall_at_k": sum(row.recall_at_k for row in rows) / len(rows),
        "ndcg_at_k": sum(row.ndcg_at_k for row in rows) / len(rows),
    }
