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
    # --- Eval-set scale expansion: broader English coverage ---
    RagRetrievalCase(
        query="How are AGVs launched when a simulation starts?",
        relevant_document_ids=("sop_startup_001",),
        category="startup",
    ),
    RagRetrievalCase(
        query="Throughput is below target. How do I improve it?",
        relevant_document_ids=("playbook_throughput_001",),
        category="throughput",
    ),
    RagRetrievalCase(
        query="What does the live status report include during a run?",
        relevant_document_ids=("sop_status_001",),
        category="status",
    ),
    RagRetrievalCase(
        query="What happens if UE5 never receives the dispatch command?",
        relevant_document_ids=("handoff_dispatch_fail_001",),
        category="handoff",
    ),
    # --- Eval-set scale expansion: Korean query variants (multilingual coverage) ---
    RagRetrievalCase(
        query="AGV 충돌이 발생하면 운영자는 가장 먼저 무엇을 해야 하나요?",
        relevant_document_ids=("sop_collision_001",),
        category="safety_ko",
    ),
    RagRetrievalCase(
        query="존 2 처리량이 떨어지고 병목률이 높을 때 대응 플레이북은?",
        relevant_document_ids=("playbook_bottleneck_001", "runbook_zone2_congestion"),
        category="bottleneck_ko",
    ),
    RagRetrievalCase(
        query="병목률이 무엇이고 어떻게 줄이나요?",
        relevant_document_ids=("playbook_bottleneck_001",),
        category="optimization_ko",
    ),
    RagRetrievalCase(
        query="KPI 정의를 알려줘. throughput, uptime, bottleneck_rate는 무엇인가요?",
        relevant_document_ids=("spec_kpi_001",),
        category="report_ko",
    ),
    RagRetrievalCase(
        query="스테이션 종류(EStationKind)에는 무엇이 있나요?",
        relevant_document_ids=("spec_station_kinds_001",),
        category="station_ko",
    ),
    RagRetrievalCase(
        query="배터리가 낮은 AGV는 디스패처가 어떻게 처리하나요?",
        relevant_document_ids=("safety_battery_001",),
        category="safety_ko",
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
    "How are AGVs launched when a simulation starts?": (
        "sop_startup_001",
        "sop_speed_001",
        "spec_station_kinds_001",
        "sop_status_001",
        "handoff_events_001",
    ),
    "Throughput is below target. How do I improve it?": (
        "playbook_throughput_001",
        "playbook_bottleneck_001",
        "spec_kpi_001",
        "runbook_zone2_congestion",
        "playbook_compare_001",
    ),
    "What does the live status report include during a run?": (
        "sop_status_001",
        "handoff_events_001",
        "spec_kpi_001",
        "safety_battery_001",
        "sop_collision_001",
    ),
    "What happens if UE5 never receives the dispatch command?": (
        "handoff_dispatch_fail_001",
        "handoff_events_001",
        "sop_status_001",
        "spec_station_meta_001",
        "sop_collision_001",
    ),
    "AGV 충돌이 발생하면 운영자는 가장 먼저 무엇을 해야 하나요?": (
        "sop_collision_001",
        "safety_zone_001",
        "sop_startup_001",
        "spec_kpi_001",
        "handoff_events_001",
    ),
    "존 2 처리량이 떨어지고 병목률이 높을 때 대응 플레이북은?": (
        "playbook_bottleneck_001",
        "runbook_zone2_congestion",
        "playbook_throughput_001",
        "spec_kpi_001",
        "safety_zone_001",
    ),
    "병목률이 무엇이고 어떻게 줄이나요?": (
        "playbook_bottleneck_001",
        "playbook_throughput_001",
        "spec_kpi_001",
        "runbook_zone2_congestion",
        "spec_station_meta_001",
    ),
    "KPI 정의를 알려줘. throughput, uptime, bottleneck_rate는 무엇인가요?": (
        "spec_kpi_001",
        "playbook_bottleneck_001",
        "playbook_compare_001",
        "playbook_throughput_001",
        "sop_status_001",
    ),
    "스테이션 종류(EStationKind)에는 무엇이 있나요?": (
        "spec_station_kinds_001",
        "spec_station_meta_001",
        "safety_battery_001",
        "sop_startup_001",
        "spec_kpi_001",
    ),
    "배터리가 낮은 AGV는 디스패처가 어떻게 처리하나요?": (
        "safety_battery_001",
        "spec_station_meta_001",
        "spec_station_kinds_001",
        "sop_status_001",
        "safety_zone_001",
    ),
}


GRAPH_RAG_RETRIEVAL_CASES: tuple[RagRetrievalCase, ...] = (
    RagRetrievalCase(
        query="Which stations in Zone 2 can handle inspection, and what was their last bottleneck rate?",
        relevant_document_ids=("ontology_station_b_inspect",),
        category="graph_multi_hop",
    ),
    RagRetrievalCase(
        query="Which Zone 1 stations can handle loading capability?",
        relevant_document_ids=("ontology_station_a_load",),
        category="graph_station_capability",
    ),
    # --- GraphRAG expressiveness expansion: Korean relational queries ---
    RagRetrievalCase(
        query="존 2에서 검사를 처리할 수 있는 스테이션과 마지막 병목률은?",
        relevant_document_ids=("ontology_station_b_inspect",),
        category="graph_multi_hop_ko",
    ),
    RagRetrievalCase(
        query="존 1 스테이션 중 적재 역량이 가능한 스테이션은?",
        relevant_document_ids=("ontology_station_a_load",),
        category="graph_station_capability_ko",
    ),
)


GRAPH_RAG_BASELINE_RANKINGS: dict[str, tuple[str, ...]] = {
    "Which stations in Zone 2 can handle inspection, and what was their last bottleneck rate?": (
        "ontology_station_b_inspect",
        "spec_station_meta_001",
        "playbook_bottleneck_001",
    ),
    "Which Zone 1 stations can handle loading capability?": (
        "ontology_station_a_load",
        "spec_station_kinds_001",
        "spec_station_meta_001",
    ),
    "존 2에서 검사를 처리할 수 있는 스테이션과 마지막 병목률은?": (
        "ontology_station_b_inspect",
        "spec_station_meta_001",
        "playbook_bottleneck_001",
    ),
    "존 1 스테이션 중 적재 역량이 가능한 스테이션은?": (
        "ontology_station_a_load",
        "spec_station_kinds_001",
        "spec_station_meta_001",
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
    # --- Eval-set scale expansion: Korean answer-grounding cases ---
    RagAnswerCase(
        case_id="answer_collision_grounded_ko",
        query="AGV 충돌이 발생하면 어떻게 대응하나요?",
        answer=(
            "충돌이 감지되면 양쪽 AGV가 정지하며, 재가동 전 경로 간섭 구간과 교차로 "
            "우선순위를 점검합니다 [source: sop_collision_001]."
        ),
        retrieved_chunks=(
            RetrievedChunk(
                document_id="sop_collision_001",
                title="AGV 충돌 발생 시 대응 절차",
                text=(
                    "두 AGV가 충돌 감지 반경 안으로 접근하면 양쪽 모두 정지한다. 재가동 전에는 "
                    "경로 간섭 구간과 교차로 우선순위 설정을 점검한다."
                ),
                score=0.92,
                source="ops_manual",
                category="sop",
            ),
        ),
        expected_cited_document_ids=("sop_collision_001",),
        required_terms=("정지", "점검"),
    ),
    RagAnswerCase(
        case_id="answer_status_grounded_ko",
        query="현재 상태를 물으면 무엇을 보고하나요?",
        answer=(
            "현재 상태는 LiveTelemetryHub를 읽어 가동 AGV 수와 셀 가동률을 보고합니다 "
            "[source: sop_status_001]."
        ),
        retrieved_chunks=(
            RetrievedChunk(
                document_id="sop_status_001",
                title="실시간 상태 조회 기준",
                text=(
                    "가동 중 현재 상태를 물으면 LiveTelemetryHub를 읽어 가동 AGV 수, AGV별 상태, "
                    "셀 가동률, 충돌 AGV를 보고한다."
                ),
                score=0.89,
                source="ops_manual",
                category="sop",
            ),
        ),
        expected_cited_document_ids=("sop_status_001",),
        required_terms=("가동률", "보고"),
    ),
    RagAnswerCase(
        case_id="answer_honest_miss_ko",
        query="AGV 배터리 팩의 공급사 보증 기간은 얼마인가요?",
        answer="not in the knowledge base",
        retrieved_chunks=(),
        expected_cited_document_ids=(),
        should_abstain=True,
    ),
)
