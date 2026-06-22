from app.benchmarks.rag_cases import (
    GRAPH_RAG_BASELINE_RANKINGS,
    GRAPH_RAG_RETRIEVAL_CASES,
    RAG_ANSWER_CASES,
    RAG_BASELINE_RANKINGS,
    RAG_RETRIEVAL_CASES,
    RagAnswerCase,
    RagRetrievalCase,
)
from app.benchmarks.rag_eval import (
    cited_document_ids,
    evaluate_answer_grounding,
    evaluate_rankings,
    ndcg_at_k,
    recall_at_k,
)
from app.domain.models import RetrievedChunk


def test_recall_at_k_counts_any_relevant_document():
    assert recall_at_k(("a", "b", "c"), {"b", "d"}, 2) == 0.5
    assert recall_at_k(("a", "b", "c"), {"b", "d"}, 1) == 0.0


def test_ndcg_rewards_early_relevant_documents():
    early = ndcg_at_k(("relevant", "other"), {"relevant"}, 2)
    late = ndcg_at_k(("other", "relevant"), {"relevant"}, 2)

    assert early == 1.0
    assert 0.0 < late < early


def test_evaluate_rankings_returns_rows_and_macro_summary():
    cases = (
        RagRetrievalCase(query="q1", relevant_document_ids=("a",), category="sop"),
        RagRetrievalCase(query="q2", relevant_document_ids=("b",), category="spec"),
    )
    rows, summary = evaluate_rankings(cases, {"q1": ("a",), "q2": ("x",)}, k=1)

    assert [row.recall_at_k for row in rows] == [1.0, 0.0]
    assert summary["recall_at_k"] == 0.5
    assert summary["ndcg_at_k"] == 0.5


def test_rag_baseline_rankings_clear_pa4_thresholds():
    _, summary = evaluate_rankings(RAG_RETRIEVAL_CASES, RAG_BASELINE_RANKINGS, k=5)

    assert summary["recall_at_k"] >= 1.0
    assert summary["ndcg_at_k"] >= 1.0


def test_graph_rag_baseline_rankings_clear_pb_thresholds():
    _, summary = evaluate_rankings(
        GRAPH_RAG_RETRIEVAL_CASES, GRAPH_RAG_BASELINE_RANKINGS, k=3
    )

    assert summary["recall_at_k"] >= 1.0
    assert summary["ndcg_at_k"] >= 1.0


def test_answer_grounding_baseline_is_faithful():
    rows, summary = evaluate_answer_grounding(RAG_ANSWER_CASES)

    assert {row.case_id for row in rows} == {
        "answer_collision_grounded",
        "answer_bottleneck_grounded",
        "answer_honest_miss",
        "answer_collision_grounded_ko",
        "answer_status_grounded_ko",
        "answer_honest_miss_ko",
    }
    assert summary["citation_rate"] == 1.0
    assert summary["faithfulness_rate"] == 1.0
    assert summary["grounded_rate"] == 1.0
    assert summary["abstention_accuracy"] == 1.0


def test_answer_grounding_flags_unsupported_uncited_claims():
    chunk = RetrievedChunk(
        document_id="sop_collision_001",
        title="SOP collision response",
        text="Stop AGVs and inspect the intersection before restart.",
        score=0.9,
    )
    cases = (
        RagAnswerCase(
            case_id="bad_answer",
            query="collision?",
            answer="Restart immediately and notify WMS.",
            retrieved_chunks=(chunk,),
            expected_cited_document_ids=("sop_collision_001",),
            required_terms=("stop", "inspect"),
            forbidden_terms=("wms",),
        ),
    )

    rows, summary = evaluate_answer_grounding(cases)

    assert cited_document_ids("Use [source: SOP collision response].", (chunk,)) == (
        "sop_collision_001",
    )
    assert rows[0].grounded is False
    assert rows[0].citation_ok is False
    assert rows[0].required_terms_ok is False
    assert rows[0].forbidden_terms_ok is False
    assert summary["grounded_rate"] == 0.0
