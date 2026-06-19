from app.benchmarks.rag_cases import RagRetrievalCase
from app.benchmarks.rag_eval import evaluate_rankings, ndcg_at_k, recall_at_k


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
