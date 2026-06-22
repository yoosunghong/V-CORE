from __future__ import annotations

import asyncio

from app.application.chat_orchestrator import ChatOrchestrator
from app.agents.llm_schemas import IntentDecision
from app.domain.models import RobotCommandName
from app.infrastructure.container import AppContainer
from app.infrastructure.llm_gateway import build_rule_based_tool_call


class _FakeLlm:
    def __init__(self, intent: str | None) -> None:
        self._intent = intent

    async def classify_intent(self, user_message: str, correlation_id: str) -> str | None:
        return self._intent


class _BoomLlm:
    async def classify_intent(self, user_message: str, correlation_id: str) -> str | None:
        raise RuntimeError("ollama down")

USER_MESSAGE = (
    "AGV를 3대로 시뮬레이션 돌리고, 처리량은 시간당 70 이상, "
    "평균 대기 12초 이하, 충돌 0건이어야 해."
)


def _is_status(text: str) -> bool:
    # The classifier is a pure function of the text; instance state is unused.
    return ChatOrchestrator._is_process_status_request(None, text)


def test_sim_request_with_kpi_targets_is_not_process_status() -> None:
    assert _is_status(USER_MESSAGE) is False


def test_plain_status_query_still_routes_to_status() -> None:
    assert _is_status("현재 공정 상태 알려줘") is True
    assert _is_status("가동률 어때?") is True


def test_llm_routing_decision_wins_when_available() -> None:
    orch = AppContainer().chat
    orch._llm = _FakeLlm("robot_command")
    # Keyword logic would call this a status read; the LLM decision overrides it.
    route, source = asyncio.run(orch._classify_route("현재 공정 상태 알려줘", "corr"))
    assert (route, source) == ("robot_command", "llm")


def test_explicit_sim_command_overrides_llm_misroute() -> None:
    orch = AppContainer().chat
    # Ollama misroutes a clear start command to a read intent; the guard pulls it back.
    orch._llm = _FakeLlm("station_action_query")
    route, source = asyncio.run(orch._classify_route("AGV 4대로 시뮬레이션 시작해줘", "corr"))
    assert (route, source) == ("robot_command", "llm_guard")


def test_guard_does_not_hijack_plain_status_query() -> None:
    orch = AppContainer().chat
    # No lifecycle verb → the LLM's read intent is respected, not overridden.
    orch._llm = _FakeLlm("process_status")
    route, source = asyncio.run(orch._classify_route("현재 AGV 속도 어때?", "corr"))
    assert (route, source) == ("process_status", "llm")


def test_routing_falls_back_to_keyword_when_llm_returns_none() -> None:
    orch = AppContainer().chat
    orch._llm = _FakeLlm(None)
    route, source = asyncio.run(orch._classify_route("현재 공정 상태 알려줘", "corr"))
    assert (route, source) == ("process_status", "keyword")


def test_routing_falls_back_to_keyword_when_llm_raises() -> None:
    orch = AppContainer().chat
    orch._llm = _BoomLlm()
    route, source = asyncio.run(orch._classify_route(USER_MESSAGE, "corr"))
    assert (route, source) == ("robot_command", "keyword")


def test_intent_schema_accepts_chat_and_knowledge_routes() -> None:
    assert IntentDecision(intent="general_chat").intent == "general_chat"
    assert IntentDecision(intent="knowledge_query").intent == "knowledge_query"


def test_graph_knowledge_query_wins_over_llm_station_action_misroute() -> None:
    orch = AppContainer().chat
    orch._llm = _FakeLlm("station_action_query")

    route, source = asyncio.run(
        orch._classify_route(
            "존 2에서 검사를 처리할 수 있는 스테이션과 마지막 병목률은?",
            "corr_graph",
        )
    )

    assert (route, source) == ("knowledge_query", "graph")


def test_explicit_station_command_is_not_hijacked_by_graph_route() -> None:
    orch = AppContainer().chat
    orch._llm = _FakeLlm("robot_command")

    route, source = asyncio.run(
        orch._classify_route("존 2의 3번 스테이션을 검사해줘", "corr_command")
    )

    assert (route, source) == ("robot_command", "llm")


def test_compare_request_routes_to_compare_runs() -> None:
    orch = AppContainer().chat
    # No LLM call needed: the deterministic compare check wins before classify_intent.
    orch._llm = _FakeLlm("robot_command")
    route, source = asyncio.run(
        orch._classify_route("방금 결과랑 아까 결과 중에 뭐가 더 나아?", "corr")
    )
    assert (route, source) == ("compare_runs", "keyword")


def test_compare_keyword_does_not_hijack_explicit_sim_command() -> None:
    orch = AppContainer().chat
    orch._llm = _FakeLlm(None)
    # Contains "비교" but is clearly a start command → stays a robot_command.
    route, _ = asyncio.run(
        orch._classify_route("비교하게 AGV 5대로 시뮬레이션 다시 돌려줘", "corr")
    )
    assert route == "robot_command"


def test_compare_recent_runs_needs_two_finished_runs() -> None:
    orch = AppContainer().chat
    message = asyncio.run(orch._compare_recent_runs("session_x", "corr"))
    assert "2개 이상" in message


def test_compare_recent_runs_builds_ab_verdict() -> None:
    from app.domain.models import (
        Simulation,
        SimulationRun,
        SimulationRunStatus,
    )

    orch = AppContainer().chat

    async def _seed_and_compare() -> str:
        sim_a = await orch._repository.create_simulation(
            Simulation(name="A", agv_count=3, speed_multiplier=1.0)
        )
        sim_b = await orch._repository.create_simulation(
            Simulation(name="B", agv_count=5, speed_multiplier=1.5)
        )
        await orch._repository.create_run(
            SimulationRun(
                simulation_id=sim_a.simulation_id,
                status=SimulationRunStatus.COMPLETED,
                kpis_json={"throughput": 60.0, "avg_wait_time": 18.0, "uptime": 0.9},
            )
        )
        await orch._repository.create_run(
            SimulationRun(
                simulation_id=sim_b.simulation_id,
                status=SimulationRunStatus.COMPLETED,
                kpis_json={"throughput": 95.0, "avg_wait_time": 8.0, "uptime": 0.97},
            )
        )
        return await orch._compare_recent_runs("session_x", "corr")

    message = asyncio.run(_seed_and_compare())
    assert "AGV 5대·1.5배속" in message  # newer run label appears
    assert "종합:" in message


def test_rule_based_tool_call_starts_sim_with_acceptance() -> None:
    tool_call = build_rule_based_tool_call(USER_MESSAGE, None)
    assert tool_call is not None
    assert tool_call.name == RobotCommandName.START_SIMULATION
    assert tool_call.arguments["agv_count"] == 3

    acceptance = {c["metric"]: c for c in tool_call.arguments["acceptance"]}
    assert acceptance["throughput"]["comparator"] == ">="
    assert acceptance["throughput"]["threshold"] == 70.0
    assert acceptance["avg_wait_sec"]["comparator"] == "<="
    assert acceptance["avg_wait_sec"]["threshold"] == 12.0
    assert acceptance["collision_count"]["comparator"] == "=="
    assert acceptance["collision_count"]["threshold"] == 0.0
