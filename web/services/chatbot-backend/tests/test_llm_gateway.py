import asyncio

from app.agents.failure_policy import LlmGatewayError
from app.agents.report_agent import ReportAgent
from app.domain.models import (
    CommandStatus,
    DomainEvent,
    ProcessTelemetry,
    RobotCommand,
    RobotCommandName,
    Station,
)
from app.infrastructure.llm_gateway import LlamaCppLlmGateway, OllamaLlmGateway, RuleBasedLlmGateway
from app.tools.router import ToolRouter


def _gateway() -> OllamaLlmGateway:
    return OllamaLlmGateway(base_url="http://ollama:11434", model="gemma4:e2b")


def test_ollama_gateway_extracts_native_tool_call() -> None:
    tool_call = _gateway()._extract_tool_call(
        {
            "message": {
                "tool_calls": [
                    {
                        "function": {
                            "name": "run_station_task",
                            "arguments": {"station_id": 2, "priority": "normal"},
                        }
                    }
                ]
            }
        }
    )

    assert tool_call is not None
    assert tool_call.name == RobotCommandName.RUN_STATION_TASK
    assert tool_call.arguments == {"station_id": 2, "priority": "normal"}


def test_ollama_gateway_extracts_json_content_fallback() -> None:
    tool_call = _gateway()._extract_tool_call(
        {"message": {"content": '{"name": "inspect_station", "arguments": {"station_id": 4}}'}}
    )

    assert tool_call is not None
    assert tool_call.name == RobotCommandName.INSPECT_STATION
    assert tool_call.arguments == {"station_id": 4}


def test_llama_cpp_gateway_normalizes_openai_tool_call_response() -> None:
    gateway = LlamaCppLlmGateway(base_url="http://llama-cpp:8080", model="local")

    normalized = gateway._normalize_openai_chat_response(
        {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "function": {
                                    "name": "set_sim_speed",
                                    "arguments": '{"speed_multiplier": 1.5}',
                                }
                            }
                        ]
                    }
                }
            ]
        }
    )
    tool_call = gateway._extract_tool_call(normalized)

    assert tool_call is not None
    assert tool_call.name == RobotCommandName.SET_SIM_SPEED
    assert tool_call.arguments == {"speed_multiplier": 1.5}


def test_rule_based_gateway_understands_korean_station_task_request() -> None:
    tool_call = asyncio.run(
        RuleBasedLlmGateway().propose_tool_call("2번 스테이션에서 작업해줘", None, "corr_test")
    )

    assert tool_call is not None
    assert tool_call.name == RobotCommandName.RUN_STATION_TASK
    assert tool_call.arguments == {"station_id": 2}


def test_rule_based_gateway_understands_sim_lifecycle_requests() -> None:
    gateway = RuleBasedLlmGateway()

    start = asyncio.run(gateway.propose_tool_call("시뮬레이션 시작해줘", None, "c"))
    assert start is not None and start.name == RobotCommandName.START_SIMULATION

    speed = asyncio.run(gateway.propose_tool_call("속도 1.5배로 바꿔", None, "c"))
    assert speed is not None and speed.name == RobotCommandName.SET_SIM_SPEED
    assert speed.arguments == {"speed_multiplier": 1.5}

    pause = asyncio.run(gateway.propose_tool_call("일시정지", None, "c"))
    assert pause is not None and pause.name == RobotCommandName.PAUSE_SIMULATION


def test_rule_based_gateway_extracts_agv_count_for_sim_start() -> None:
    tool_call = asyncio.run(
        RuleBasedLlmGateway().propose_tool_call("AGV 10대로 시뮬레이션 시작해줘", None, "c")
    )

    assert tool_call is not None
    assert tool_call.name == RobotCommandName.START_SIMULATION
    assert tool_call.arguments == {"agv_count": 10}


def test_rule_based_gateway_understands_add_agv_commands() -> None:
    gateway = RuleBasedLlmGateway()

    call1 = asyncio.run(gateway.propose_tool_call("Add 1 AGV", None, "c"))
    assert call1 is not None
    assert call1.name == RobotCommandName.START_SIMULATION
    assert call1.arguments == {"agv_count": 1}

    call2 = asyncio.run(gateway.propose_tool_call("AGV 2대 추가해줘", None, "c"))
    assert call2 is not None
    assert call2.name == RobotCommandName.START_SIMULATION
    assert call2.arguments == {"agv_count": 2}

    call3 = asyncio.run(gateway.propose_tool_call("1대 더 추가", None, "c"))
    assert call3 is not None
    assert call3.name == RobotCommandName.START_SIMULATION
    assert call3.arguments == {"agv_count": 1}


def test_ollama_gateway_falls_back_when_tool_response_is_empty() -> None:
    gateway = _gateway()

    async def empty_response(payload: dict, correlation_id: str) -> dict:
        return {"message": {"content": ""}}

    gateway._post_chat = empty_response  # type: ignore[method-assign]

    tool_call = asyncio.run(gateway.propose_tool_call("2번 스테이션 작업해줘", None, "corr_test"))

    assert tool_call is not None
    assert tool_call.name == RobotCommandName.RUN_STATION_TASK
    assert tool_call.arguments == {"station_id": 2}


def test_user_move_request_is_not_a_tool_call() -> None:
    """move_to_station is internal-only: a user "move/이동" request yields no tool call."""
    gateway = _gateway()

    async def empty_response(payload: dict, correlation_id: str) -> dict:
        return {"message": {"content": ""}}

    gateway._post_chat = empty_response  # type: ignore[method-assign]

    tool_call = asyncio.run(gateway.propose_tool_call("2번 스테이션으로 이동해줘", None, "corr_move"))

    assert tool_call is None


def test_ollama_gateway_repairs_invalid_tool_response_on_retry() -> None:
    gateway = _gateway()
    responses = [
        {"message": {"content": '{"name": "set_sim_speed", "arguments": {"speed_multiplier": "fast"}}'}},
        {"message": {"content": '{"name": "set_sim_speed", "arguments": {"speed_multiplier": 2.0}}'}},
    ]

    async def sequence_response(payload: dict, correlation_id: str) -> dict:
        return responses.pop(0)

    gateway._post_chat = sequence_response  # type: ignore[method-assign]

    tool_call = asyncio.run(gateway.propose_tool_call("speed to 2x", None, "corr_retry"))

    assert tool_call is not None
    assert tool_call.name == RobotCommandName.SET_SIM_SPEED
    assert tool_call.arguments == {"speed_multiplier": 2.0}
    assert gateway.last_tool_attempts == [
        {"attempt": 1, "valid": False, "error": "speed_multiplier must be a number"},
        {"attempt": 2, "valid": True},
    ]


# --------------------------------------------------------------------------- #
# Phase 2-B — validation-layer fixes (decline support + range checking)
# --------------------------------------------------------------------------- #


def _gateway_phase2b() -> OllamaLlmGateway:
    """Layer-ON gateway with both Phase-2-B fixes active (mirrors the A2/B2 cells)."""
    return OllamaLlmGateway(
        base_url="http://ollama:11434",
        model="gemma4:e2b",
        structured_retry_count=1,
        enable_rule_based_fallback=True,
        enable_decline_retry=True,
        enable_range_validation=True,
    )


def test_tool_router_range_checks_reject_out_of_range() -> None:
    from app.domain.models import ToolCall
    from app.tools.contracts import ToolValidationError

    router = ToolRouter()

    def rejected(name: RobotCommandName, args: dict) -> bool:
        try:
            router.validate(ToolCall(name=name, arguments=args), check_ranges=True)
            return False
        except ToolValidationError:
            return True

    # Out-of-range probes are rejected only when check_ranges is on.
    assert rejected(RobotCommandName.MOVE_TO_STATION, {"station_id": -1})
    assert rejected(RobotCommandName.INSPECT_STATION, {"station_id": 999})
    assert rejected(RobotCommandName.SET_SIM_SPEED, {"speed_multiplier": 0})
    assert rejected(RobotCommandName.SET_SIM_SPEED, {"speed_multiplier": -2})
    assert rejected(RobotCommandName.START_SIMULATION, {"agv_count": "five"})
    # Valid gold-positive values still pass.
    router.validate(ToolCall(name=RobotCommandName.INSPECT_STATION, arguments={"station_id": 12}), check_ranges=True)
    router.validate(ToolCall(name=RobotCommandName.SET_SIM_SPEED, arguments={"speed_multiplier": 1.5}), check_ranges=True)
    # Without range checks the old type-only behavior is preserved.
    router.validate(ToolCall(name=RobotCommandName.MOVE_TO_STATION, arguments={"station_id": -1}))


def test_phase2b_layer_honors_clean_decline_without_coercion() -> None:
    gateway = _gateway_phase2b()

    async def empty_response(payload: dict, correlation_id: str) -> dict:
        return {"message": {"content": ""}}

    gateway._post_chat = empty_response  # type: ignore[method-assign]

    # A negative-control prompt that contains a station keyword: the rule-based
    # fallback would act on it, but a clean LLM decline must be honored as no-tool.
    tool_call = asyncio.run(gateway.propose_tool_call("3번 스테이션 날씨 어때?", None, "corr_decline"))

    assert tool_call is None
    assert gateway.last_tool_attempts == [{"attempt": 1, "valid": True, "declined": True}]


def test_phase2b_layer_declines_out_of_range_after_repair() -> None:
    gateway = _gateway_phase2b()
    out_of_range = {"message": {"content": '{"name": "move_to_station", "arguments": {"station_id": -1}}'}}

    async def always_out_of_range(payload: dict, correlation_id: str) -> dict:
        return out_of_range

    gateway._post_chat = always_out_of_range  # type: ignore[method-assign]

    # First pass is out-of-range -> repair retry -> still out-of-range -> the
    # range-checked fallback rejects it too -> terminal decline.
    tool_call = asyncio.run(gateway.propose_tool_call("Move to station -1.", None, "corr_invalid"))

    assert tool_call is None
    assert len(gateway.last_tool_attempts) == 2
    assert all(attempt["valid"] is False for attempt in gateway.last_tool_attempts)


def test_phase2b_layer_returns_valid_first_pass_tool() -> None:
    gateway = _gateway_phase2b()

    async def valid_response(payload: dict, correlation_id: str) -> dict:
        return {"message": {"content": '{"name": "inspect_station", "arguments": {"station_id": 2}}'}}

    gateway._post_chat = valid_response  # type: ignore[method-assign]

    tool_call = asyncio.run(gateway.propose_tool_call("inspect station 2", None, "corr_valid"))

    assert tool_call is not None
    assert tool_call.name == RobotCommandName.INSPECT_STATION
    assert tool_call.arguments == {"station_id": 2}
    assert gateway.last_tool_attempts == [{"attempt": 1, "valid": True}]


def test_ollama_gateway_extracts_plan_steps() -> None:
    steps = _gateway()._extract_plan_steps(
        {"message": {"content": '{"steps":["classify intent","choose route","validate tool call"]}'}}
    )

    assert steps == ["classify intent", "choose route", "validate tool call"]


def test_tool_router_exports_ollama_tool_schemas() -> None:
    tools = ToolRouter().ollama_tools()

    run_task = next(tool for tool in tools if tool["function"]["name"] == "run_station_task")
    assert run_task["type"] == "function"
    assert run_task["function"]["parameters"]["required"] == ["station_id"]
    assert run_task["function"]["parameters"]["additionalProperties"] is False
    assert any(tool["function"]["name"] == "set_sim_speed" for tool in tools)


def test_ollama_gateway_uses_compact_station_context() -> None:
    gateway = _gateway()
    station_context = gateway._compact_station_context(
        Station(station_id=2, station_type="work", task_ready=True, cell_id="cell_demo", zone="A")
    )
    assert station_context == (
        '{"station_id":2,"station_type":"work","task_ready":true,'
        '"cell_id":"cell_demo","zone":"A"}'
    )


def test_report_agent_falls_back_when_llm_report_is_empty() -> None:
    class EmptyReportGateway:
        async def generate_plan_steps(self, user_message: str, correlation_id: str) -> list[str]:
            return []

        async def propose_tool_call(self, user_message: str, station: Station | None, correlation_id: str):
            return None

        async def generate_report(self, event, command, correlation_id: str, evaluation=None, knowledge=None) -> str:
            raise LlmGatewayError("empty report")

    event = DomainEvent(
        event_type="robot.command.completed",
        correlation_id="corr",
        session_id="session",
        command_id="cmd",
    )
    command = RobotCommand(
        command_id="cmd",
        session_id="session",
        command_name=RobotCommandName.RUN_STATION_TASK,
        correlation_id="corr",
        idempotency_key="idem",
        parameters={"station_id": 2},
        status=CommandStatus.COMPLETED,
    )

    report = asyncio.run(ReportAgent(EmptyReportGateway()).generate_report(event, command, "corr"))
    assert report == "Station 2 task is complete."


def test_report_agent_fallback_appends_evaluation_narrative() -> None:
    class EmptyReportGateway:
        async def generate_plan_steps(self, user_message: str, correlation_id: str) -> list[str]:
            return []

        async def propose_tool_call(self, user_message: str, station: Station | None, correlation_id: str):
            return None

        async def generate_report(self, event, command, correlation_id: str, evaluation=None, knowledge=None) -> str:
            raise LlmGatewayError("empty report")

    event = DomainEvent(
        event_type="robot.command.completed",
        correlation_id="corr",
        session_id="session",
        command_id="cmd",
        payload={
            "kpis": {
                "throughput": 72.0,
                "avg_wait_time": 6.0,
                "collision_risk": 0.1,
                "uptime": 0.97,
                "heatmap_grid": [0.0] * 23 + [9.0],
                "heatmap_res_x": 24,
                "heatmap_res_y": 1,
            },
            "verdict": {"passed": True, "passed_labels": ["throughput"], "failed_labels": []},
        },
    )
    command = RobotCommand(
        command_id="cmd",
        session_id="session",
        command_name=RobotCommandName.START_SIMULATION,
        correlation_id="corr",
        idempotency_key="idem",
        parameters={},
        status=CommandStatus.COMPLETED,
    )

    report = asyncio.run(ReportAgent(EmptyReportGateway()).generate_report(event, command, "corr"))
    assert "AI 종합 평가" in report
    assert "혼잡 히트맵" in report
    assert "A · 우수" in report


def test_process_telemetry_model_roundtrips() -> None:
    telemetry = ProcessTelemetry(
        throughput=68.2,
        active_agvs=3,
        avg_wait_time=12.0,
        collision_risk=0.0,
        uptime=0.97,
    )
    assert telemetry.model_dump()["throughput"] == 68.2
