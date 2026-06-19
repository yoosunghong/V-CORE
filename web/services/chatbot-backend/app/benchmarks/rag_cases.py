from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RagRetrievalCase:
    query: str
    relevant_document_ids: tuple[str, ...]
    category: str


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
