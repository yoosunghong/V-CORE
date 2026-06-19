import pytest

from app.application.chat_orchestrator import ChatOrchestrator
from app.application.robot_orchestrator import RobotCommandOrchestrator
from app.domain.models import RetrievedChunk
from app.infrastructure.control_client import DemoControlServerClient
from app.infrastructure.event_bus import InMemoryEventBus
from app.infrastructure.iot_client import DemoIotCommandClient
from app.infrastructure.knowledge_gateway import NullKnowledgeGateway, lexical_rerank
from app.infrastructure.llm_gateway import OllamaLlmGateway, RuleBasedLlmGateway, format_knowledge_block
from app.infrastructure.repositories import InMemorySessionRepository


class StubKnowledgeGateway:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.queries: list[str] = []

    async def retrieve(self, query, correlation_id, *, top_k=5, filters=None):
        self.queries.append(query)
        return self._chunks


class CapturingLlmGateway(RuleBasedLlmGateway):
    """Rule-based gateway that records the knowledge passed to generate_chat_response."""

    def __init__(self) -> None:
        self.chat_knowledge: list[RetrievedChunk] | None = None

    async def classify_intent(self, user_message, correlation_id):
        return "general_chat"

    async def generate_chat_response(self, user_message, history, correlation_id, knowledge=None):
        self.chat_knowledge = knowledge
        return "ok"


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
async def test_general_chat_without_rag_emits_no_retrieval_event():
    llm = CapturingLlmGateway()
    orchestrator = _orchestrator(llm, NullKnowledgeGateway())

    _, _, _, events = await orchestrator.handle_user_message(
        session_id="s2", user_text="안녕하세요", correlation_id="corr_no_rag"
    )

    assert llm.chat_knowledge == []
    assert not any(e.event_type == "agent.retrieval" for e in events)
