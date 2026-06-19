from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import RetrievedChunk


@dataclass(frozen=True)
class RagRetrievalCase:
    query: str
    relevant_document_ids: tuple[str, ...]
    category: str


@dataclass(frozen=True)
class RagAnswerCase:
    case_id: str
    query: str
    answer: str
    retrieved_chunks: tuple[RetrievedChunk, ...]
    expected_cited_document_ids: tuple[str, ...]
    required_terms: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    should_abstain: bool = False


RAG_RETRIEVAL_CASES: tuple[RagRetrievalCase, ...] = (
    RagRetrievalCase(
        query="AGV collision happened. What should the operator do first?",
        relevant_document_ids=("sop_collision_001",),
        category="safety",
    ),
    RagRetrievalCase(
        query="Zone 2 throughput dropped and bottleneck rate is high. What is the playbook?",
        relevant_document_ids=("playbook_bottleneck_001", "runbook_zone2_congestion"),
        category="bottleneck",
    ),
    RagRetrievalCase(
        query="What does SOP say about reducing AGV count when congestion grows?",
        relevant_document_ids=("playbook_bottleneck_001",),
        category="optimization",
    ),
    RagRetrievalCase(
        query="How should the report explain a KPI verdict with wait time and throughput?",
        relevant_document_ids=("spec_kpi_001", "playbook_compare_001"),
        category="report",
    ),
    RagRetrievalCase(
        query="Which charger or station capability rules matter before dispatch?",
        relevant_document_ids=("spec_station_meta_001", "spec_station_kinds_001", "safety_battery_001"),
        category="station",
    ),
    RagRetrievalCase(
        query="What should the demo handoff say about Unreal and backend integration?",
        relevant_document_ids=("handoff_events_001",),
        category="handoff",
    ),
)


RAG_BASELINE_RANKINGS: dict[str, tuple[str, ...]] = {
    "AGV collision happened. What should the operator do first?": (
        "sop_collision_001",
        "safety_battery_001",
        "handoff_events_001",
        "spec_kpi_001",
        "playbook_bottleneck_001",
    ),
    "Zone 2 throughput dropped and bottleneck rate is high. What is the playbook?": (
        "playbook_bottleneck_001",
        "runbook_zone2_congestion",
        "spec_kpi_001",
        "playbook_compare_001",
        "sop_collision_001",
    ),
    "What does SOP say about reducing AGV count when congestion grows?": (
        "playbook_bottleneck_001",
        "runbook_zone2_congestion",
        "spec_kpi_001",
        "spec_station_meta_001",
        "safety_battery_001",
    ),
    "How should the report explain a KPI verdict with wait time and throughput?": (
        "spec_kpi_001",
        "playbook_compare_001",
        "playbook_bottleneck_001",
        "handoff_events_001",
        "sop_collision_001",
    ),
    "Which charger or station capability rules matter before dispatch?": (
        "spec_station_meta_001",
        "spec_station_kinds_001",
        "safety_battery_001",
        "handoff_events_001",
        "playbook_bottleneck_001",
    ),
    "What should the demo handoff say about Unreal and backend integration?": (
        "handoff_events_001",
        "spec_kpi_001",
        "playbook_compare_001",
        "spec_station_meta_001",
        "sop_collision_001",
    ),
}


RAG_ANSWER_CASES: tuple[RagAnswerCase, ...] = (
    RagAnswerCase(
        case_id="answer_collision_grounded",
        query="AGV collision happened. What should the operator do first?",
        answer=(
            "Stop the AGVs first, preserve the intersection state, and inspect before restart "
            "[source: SOP collision response]."
        ),
        retrieved_chunks=(
            RetrievedChunk(
                document_id="sop_collision_001",
                title="SOP collision response",
                text=(
                    "When an AGV collision occurs, stop the AGVs, preserve the intersection state, "
                    "inspect the route, and restart only after clearance."
                ),
                score=0.91,
                source="ops_manual",
                category="sop",
            ),
        ),
        expected_cited_document_ids=("sop_collision_001",),
        required_terms=("stop", "inspect", "restart"),
    ),
    RagAnswerCase(
        case_id="answer_bottleneck_grounded",
        query="Zone 2 throughput dropped and bottleneck rate is high. What is the playbook?",
        answer=(
            "For Zone 2 congestion, reduce the active AGV count and rebalance dispatch until "
            "throughput recovers [source: Zone 2 bottleneck playbook]."
        ),
        retrieved_chunks=(
            RetrievedChunk(
                document_id="playbook_bottleneck_001",
                title="Zone 2 bottleneck playbook",
                text=(
                    "When Zone 2 throughput drops and bottleneck rate rises, reduce the active "
                    "AGV count, rebalance dispatch, and compare the next run against throughput "
                    "and wait-time KPIs."
                ),
                score=0.88,
                source="ops_manual",
                category="playbook",
            ),
        ),
        expected_cited_document_ids=("playbook_bottleneck_001",),
        required_terms=("zone 2", "reduce", "agv", "throughput"),
    ),
    RagAnswerCase(
        case_id="answer_honest_miss",
        query="What is the vendor warranty period for the AGV battery pack?",
        answer="not in the knowledge base",
        retrieved_chunks=(),
        expected_cited_document_ids=(),
        should_abstain=True,
    ),
)
