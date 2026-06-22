import httpx
import pytest

from app.application.chat_orchestrator import ChatOrchestrator
from app.application.robot_orchestrator import RobotCommandOrchestrator
from app.domain.models import RetrievedChunk, SimulationRun
from app.domain.ontology import GraphRagRetriever, OntologyGraphBuilder
from app.infrastructure.control_client import DemoControlServerClient
from app.infrastructure.event_bus import InMemoryEventBus
from app.infrastructure.iot_client import DemoIotCommandClient
from app.infrastructure.knowledge_gateway import (
    HybridGraphKnowledgeGateway,
    NullKnowledgeGateway,
    QdrantKnowledgeGateway,
    lexical_rerank,
)
from app.infrastructure.llm_gateway import OllamaLlmGateway, RuleBasedLlmGateway, format_knowledge_block
from app.infrastructure.repositories import InMemorySessionRepository


class StubKnowledgeGateway:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.queries: list[str] = []

    async def retrieve(self, query, correlation_id, *, top_k=5, filters=None):
        self.queries.append(query)
        return self._chunks


class RecordingVectorGateway:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.queries: list[str] = []

    async def retrieve(self, query, correlation_id, *, top_k=5, filters=None):
        self.queries.append(query)
        return self._chunks[:top_k]


class CapturingLlmGateway(RuleBasedLlmGateway):
    """Rule-based gateway that records the knowledge passed to generate_chat_response."""

    def __init__(self) -> None:
        self.chat_knowledge: list[RetrievedChunk] | None = None

    async def classify_intent(self, user_message, correlation_id):
        return "general_chat"

    async def generate_chat_response(self, user_message, history, correlation_id, knowledge=None):
        self.chat_knowledge = knowledge
        return "ok"


class StationActionMisroutingLlm(CapturingLlmGateway):
    """Models the production failure where a knowledge read looked operational."""

    async def classify_intent(self, user_message, correlation_id):
        return "station_action_query"


def _orchestrator(llm, knowledge):
    repository = InMemorySessionRepository()
    events = InMemoryEventBus()
    iot = DemoIotCommandClient()
    return ChatOrchestrator(
        repository=repository,
        control_client=DemoControlServerClient(),
        iot_telemetry=iot,
        llm=llm,
        robot_commands=RobotCommandOrchestrator(repository=repository, iot_client=iot, events=events),
        events=events,
        knowledge=knowledge,
    )


@pytest.mark.asyncio
async def test_null_gateway_returns_empty():
    assert await NullKnowledgeGateway().retrieve("anything", "corr") == []


@pytest.mark.asyncio
async def test_qdrant_cloud_auth_and_local_fallback_do_not_share_secret():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "cloud.example":
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            json={"result": [{"id": "local-hit", "score": 0.9, "payload": {}}]},
            request=request,
        )

    gateway = QdrantKnowledgeGateway(
        qdrant_url="https://cloud.example",
        qdrant_api_key="cloud-secret",
        qdrant_fallback_url="http://qdrant:6333",
        collection="vcore_operations_ko",
        embed_base_url="http://ollama:11434",
        embed_model="bge-m3",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        hits = await gateway._search(client, [0.1, 0.2], 5, None)

    assert hits[0]["id"] == "local-hit"
    assert requests[0].headers["api-key"] == "cloud-secret"
    assert "api-key" not in requests[1].headers
    assert requests[1].url.host == "qdrant"


def test_format_knowledge_block_none():
    assert format_knowledge_block(None) == "none"
    assert format_knowledge_block([]) == "none"


def test_format_knowledge_block_renders_titles_and_source():
    block = format_knowledge_block(
        [RetrievedChunk(document_id="d1", title="충돌 대응", text="절차 ...", score=0.7, source="ops_manual")]
    )
    assert "[출처: 충돌 대응]" in block and "ops_manual" in block


def test_lexical_rerank_promotes_query_matching_chunk():
    chunks = [
        RetrievedChunk(
            document_id="general",
            title="General KPI policy",
            text="Throughput and uptime are reviewed after each run.",
            score=0.72,
            vector_score=0.72,
        ),
        RetrievedChunk(
            document_id="collision",
            title="Collision halt response",
            text="When collision risk appears, stop AGVs and inspect the intersection.",
            score=0.7,
            vector_score=0.7,
        ),
    ]

    reranked = lexical_rerank("collision stop inspection", chunks)

    assert reranked[0].document_id == "collision"
    assert reranked[0].rerank_score is not None


@pytest.mark.asyncio
async def test_graph_rag_retrieves_zone_capability_and_latest_bottleneck():
    repository = InMemorySessionRepository()
    await repository.create_run(
        SimulationRun(
            simulation_id="sim_graph",
            run_id="run_graph_latest",
            kpis_json={"bottleneck_rate": 0.31, "bottleneck_zone": "B"},
        )
    )
    stations = await DemoControlServerClient().list_stations("corr_graph")

    chunks = GraphRagRetriever().retrieve(
        "Which stations in Zone 2 can handle inspection, and what was their last bottleneck rate?",
        stations,
        await repository.list_runs(),
    )

    assert chunks[0].category == "graph_ontology"
    assert chunks[0].source == "ontology_graph"
    assert chunks[0].document_id == "ontology_station_b_inspect"
    assert "Station 3" in chunks[0].text
    assert "Latest cell bottleneck_rate: 0.31" in chunks[0].text


@pytest.mark.asyncio
async def test_graph_rag_handles_korean_relational_query():
    repository = InMemorySessionRepository()
    await repository.create_run(
        SimulationRun(
            simulation_id="sim_graph_ko",
            run_id="run_graph_ko",
            kpis_json={"bottleneck_rate": 0.31, "bottleneck_zone": "B"},
        )
    )
    stations = await DemoControlServerClient().list_stations("corr_graph_ko")
    retriever = GraphRagRetriever()

    query = "존 2에서 검사를 처리할 수 있는 스테이션과 마지막 병목률은?"
    assert retriever.is_relational_query(query)

    chunks = retriever.retrieve(query, stations, await repository.list_runs())

    assert chunks[0].document_id == "ontology_station_b_inspect"
    assert "Station 3" in chunks[0].text


@pytest.mark.asyncio
async def test_graph_rag_attributes_zone_level_bottleneck_per_station():
    repository = InMemorySessionRepository()
    await repository.create_run(
        SimulationRun(
            simulation_id="sim_graph_zone",
            run_id="run_graph_zone",
            kpis_json={"bottleneck_rate": 0.39, "zone_heatmap": {"B": 0.47, "A": 0.12}},
        )
    )
    stations = await DemoControlServerClient().list_stations("corr_graph_zone")

    chunks = GraphRagRetriever().retrieve(
        "Which stations in Zone 2 can handle inspection, and what was their last bottleneck rate?",
        stations,
        await repository.list_runs(),
    )

    text = chunks[0].text
    assert "Last zone bottleneck_rate: 0.47" in text
    assert "Latest cell bottleneck_rate: 0.39" in text


@pytest.mark.asyncio
async def test_graph_builder_memoizes_until_inputs_change():
    repository = InMemorySessionRepository()
    await repository.create_run(
        SimulationRun(
            simulation_id="sim_cache",
            run_id="run_cache_1",
            kpis_json={"bottleneck_rate": 0.31},
        )
    )
    stations = await DemoControlServerClient().list_stations("corr_cache")
    builder = OntologyGraphBuilder()

    runs = await repository.list_runs()
    first = builder.build(stations, runs)
    second = builder.build(stations, list(runs))  # equal content, fresh list

    assert second is first  # cached projection reused, not rebuilt
    assert builder.builds == 1

    await repository.create_run(
        SimulationRun(
            simulation_id="sim_cache",
            run_id="run_cache_2",
            kpis_json={"bottleneck_rate": 0.18},
        )
    )
    third = builder.build(stations, await repository.list_runs())

    assert third is not first  # new run invalidates the fingerprint -> rebuild
    assert builder.builds == 2


@pytest.mark.asyncio
async def test_graph_rag_reuses_cached_graph_across_queries():
    repository = InMemorySessionRepository()
    await repository.create_run(
        SimulationRun(
            simulation_id="sim_reuse",
            run_id="run_reuse",
            kpis_json={"bottleneck_rate": 0.31, "bottleneck_zone": "B"},
        )
    )
    stations = await DemoControlServerClient().list_stations("corr_reuse")
    runs = await repository.list_runs()
    builder = OntologyGraphBuilder()
    retriever = GraphRagRetriever(builder=builder)

    for query in (
        "Which stations in Zone 2 can handle inspection?",
        "존 2에서 검사를 처리할 수 있는 스테이션은?",
        "Which stations in Zone 1 can handle loading?",
    ):
        assert retriever.retrieve(query, stations, runs)

    assert builder.builds == 1  # three relational queries, one build


@pytest.mark.asyncio
async def test_hybrid_gateway_routes_relational_query_to_graph_without_vector_call():
    repository = InMemorySessionRepository()
    await repository.create_run(
        SimulationRun(
            simulation_id="sim_graph",
            run_id="run_graph_latest",
            kpis_json={"bottleneck_rate": 0.22},
        )
    )
    vector = RecordingVectorGateway(
        [RetrievedChunk(document_id="vector", title="Vector", text="fallback", score=0.5)]
    )
    gateway = HybridGraphKnowledgeGateway(vector, DemoControlServerClient(), repository)

    chunks = await gateway.retrieve(
        "Which stations in Zone 2 can handle inspection capability?",
        "corr_graph",
    )

    assert chunks[0].document_id == "ontology_station_b_inspect"
    assert vector.queries == []


@pytest.mark.asyncio
async def test_hybrid_gateway_uses_vector_for_free_text_query():
    repository = InMemorySessionRepository()
    vector = RecordingVectorGateway(
        [RetrievedChunk(document_id="sop_collision_001", title="Collision", text="stop", score=0.9)]
    )
    gateway = HybridGraphKnowledgeGateway(vector, DemoControlServerClient(), repository)

    chunks = await gateway.retrieve("What should I do after an AGV collision?", "corr_vector")

    assert chunks[0].document_id == "sop_collision_001"
    assert vector.queries == ["What should I do after an AGV collision?"]


def test_chat_prompt_contains_grounding_guard_without_knowledge():
    captured = {}

    class Gateway(OllamaLlmGateway):
        async def _post_chat(self, payload, correlation_id):
            captured["payload"] = payload
            return {"message": {"content": "ok"}}

    gateway = Gateway(base_url="http://unused", model="unused")

    async def run():
        await gateway.generate_chat_response("unknown policy?", [], "corr", knowledge=[])

    import asyncio

    asyncio.run(run())
    system = captured["payload"]["messages"][0]["content"]
    assert "not in the knowledge base" in system


@pytest.mark.asyncio
async def test_general_chat_threads_retrieved_knowledge_into_llm():
    chunk = RetrievedChunk(
        document_id="sop_collision_001", title="AGV 충돌 대응", text="충돌 시 정지", score=0.71, source="ops_manual"
    )
    llm = CapturingLlmGateway()
    knowledge = StubKnowledgeGateway([chunk])
    orchestrator = _orchestrator(llm, knowledge)

    _, _, _, events = await orchestrator.handle_user_message(
        session_id="s1", user_text="충돌이 나면 어떻게 대응해?", correlation_id="corr_rag"
    )

    assert knowledge.queries == ["충돌이 나면 어떻게 대응해?"]
    assert llm.chat_knowledge == [chunk]
    retrieval = next(e for e in events if e.event_type == "agent.retrieval")
    assert retrieval.payload["hits"][0]["document_id"] == "sop_collision_001"


@pytest.mark.asyncio
async def test_korean_graph_query_routes_to_retrieval_before_llm_misclassification():
    query = "존 2에서 검사를 처리할 수 있는 스테이션과 마지막 병목률은?"
    chunk = RetrievedChunk(
        document_id="ontology_station_b_inspect",
        title="Ontology: Zone B stations for capability inspect",
        text="Station 3; Last zone bottleneck_rate: 0.47",
        score=1.0,
        source="ontology_graph",
    )
    llm = StationActionMisroutingLlm()
    knowledge = StubKnowledgeGateway([chunk])
    orchestrator = _orchestrator(llm, knowledge)

    message, command_id, status, events = await orchestrator.handle_user_message(
        session_id="s_graph_route",
        user_text=query,
        correlation_id="corr_graph_route",
    )

    assert message.content == "ok"
    assert command_id is None
    assert status is None
    assert knowledge.queries == [query]
    assert llm.chat_knowledge == [chunk]
    route = next(event for event in events if event.event_type == "agent.route.selected")
    assert route.payload == {"route": "knowledge_query", "source": "graph"}
    plan = next(event for event in events if event.event_type == "agent.plan.started")
    assert plan.payload["source"] == "graph_rag"
    assert any("Graph RAG" in step for step in plan.payload["steps"])


@pytest.mark.asyncio
async def test_general_chat_without_rag_emits_no_retrieval_event():
    llm = CapturingLlmGateway()
    orchestrator = _orchestrator(llm, NullKnowledgeGateway())

    _, _, _, events = await orchestrator.handle_user_message(
        session_id="s2", user_text="안녕하세요", correlation_id="corr_no_rag"
    )

    assert llm.chat_knowledge == []
    assert not any(e.event_type == "agent.retrieval" for e in events)
