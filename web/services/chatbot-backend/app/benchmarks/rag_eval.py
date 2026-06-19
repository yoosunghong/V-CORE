from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.benchmarks.rag_cases import RagAnswerCase, RagRetrievalCase
from app.domain.models import RetrievedChunk


@dataclass(frozen=True)
class RagEvalRow:
    query: str
    category: str
    relevant_document_ids: tuple[str, ...]
    returned_document_ids: tuple[str, ...]
    recall_at_k: float
    ndcg_at_k: float


@dataclass(frozen=True)
class RagAnswerEvalRow:
    case_id: str
    query: str
    cited_document_ids: tuple[str, ...]
    expected_cited_document_ids: tuple[str, ...]
    citation_ok: bool
    required_terms_ok: bool
    forbidden_terms_ok: bool
    abstention_ok: bool
    faithfulness_score: float
    grounded: bool


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


def evaluate_answer_grounding(
    cases: list[RagAnswerCase] | tuple[RagAnswerCase, ...],
) -> tuple[list[RagAnswerEvalRow], dict[str, float]]:
    rows = [_score_answer_case(case) for case in cases]
    if not rows:
        return rows, {
            "citation_rate": 0.0,
            "faithfulness_rate": 0.0,
            "grounded_rate": 0.0,
            "abstention_accuracy": 0.0,
        }
    return rows, {
        "citation_rate": _mean(row.citation_ok for row in rows),
        "faithfulness_rate": sum(row.faithfulness_score for row in rows) / len(rows),
        "grounded_rate": _mean(row.grounded for row in rows),
        "abstention_accuracy": _mean(row.abstention_ok for row in rows),
    }


def cited_document_ids(answer: str, chunks: tuple[RetrievedChunk, ...]) -> tuple[str, ...]:
    normalized = _normalize(answer)
    cited: list[str] = []
    for chunk in chunks:
        title = _normalize(chunk.title)
        document_id = _normalize(chunk.document_id)
        source = _normalize(chunk.source)
        if document_id and document_id in normalized:
            cited.append(chunk.document_id)
        elif title and title in normalized:
            cited.append(chunk.document_id)
        elif source and f"source: {source}" in normalized:
            cited.append(chunk.document_id)
    return tuple(dict.fromkeys(cited))


def _score_answer_case(case: RagAnswerCase) -> RagAnswerEvalRow:
    answer = _normalize(case.answer)
    context = _normalize(
        " ".join(
            f"{chunk.document_id} {chunk.title} {chunk.source} {chunk.category} {chunk.text}"
            for chunk in case.retrieved_chunks
        )
    )
    cited = cited_document_ids(case.answer, case.retrieved_chunks)
    expected_citations = set(case.expected_cited_document_ids)
    if case.should_abstain:
        abstention_ok = "not in the knowledge base" in answer
        citation_ok = True
        required_terms_ok = True
        forbidden_terms_ok = True
        faithfulness = 1.0 if abstention_ok else 0.0
        grounded = abstention_ok
    else:
        abstention_ok = "not in the knowledge base" not in answer
        citation_ok = bool(set(cited) & expected_citations) if expected_citations else True
        required_terms_ok = all(_normalize(term) in answer and _normalize(term) in context for term in case.required_terms)
        forbidden_terms_ok = not any(_normalize(term) in answer for term in case.forbidden_terms)
        checks = (citation_ok, required_terms_ok, forbidden_terms_ok, abstention_ok)
        faithfulness = sum(1.0 for check in checks if check) / len(checks)
        grounded = citation_ok and required_terms_ok and forbidden_terms_ok and abstention_ok
    return RagAnswerEvalRow(
        case_id=case.case_id,
        query=case.query,
        cited_document_ids=cited,
        expected_cited_document_ids=case.expected_cited_document_ids,
        citation_ok=citation_ok,
        required_terms_ok=required_terms_ok,
        forbidden_terms_ok=forbidden_terms_ok,
        abstention_ok=abstention_ok,
        faithfulness_score=faithfulness,
        grounded=grounded,
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()


def _mean(flags: Iterable[bool]) -> float:
    values = list(flags)
    return sum(1.0 for flag in values if flag) / len(values) if values else 0.0
