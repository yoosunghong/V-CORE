from __future__ import annotations

import operator
import time
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.failure_policy import LlmGatewayError
from app.domain.models import (
    ChatMessage,
    CommandStatus,
    DomainEvent,
    MessageRole,
    RetrievedChunk,
    RobotCommand,
    RobotCommandName,
    Station,
    ToolCall,
)
from app.tools.contracts import ToolValidationError, ValidatedToolCall


class MultiResponseState(TypedDict, total=False):
    session_id: str
    user_text: str
    correlation_id: str
    idempotency_key: str
    user_message: ChatMessage
    assistant: ChatMessage
    events: Annotated[list[DomainEvent], operator.add]
    trace: Annotated[list[dict[str, Any]], operator.add]
    route: str
    retrieved: list[RetrievedChunk]
    station: Station | None
    validated_tool_call: ValidatedToolCall | None
    command: RobotCommand
    command_id: str | None
    status: CommandStatus | None
    result: tuple[ChatMessage, str | None, CommandStatus | None, list[DomainEvent]]


class LangGraphMultiResponseAgent:
    """Coordinates the chat response lifecycle as a LangGraph state machine."""

    def __init__(self, orchestrator: Any, checkpointer: Any | None = None) -> None:
        self._orchestrator = orchestrator
        self._checkpointer = checkpointer or MemorySaver()
        self._graph = self._build_graph()

    async def handle(
        self,
        session_id: str,
        user_text: str,
        correlation_id: str,
        idempotency_key: str,
    ) -> tuple[ChatMessage, str | None, CommandStatus | None, list[DomainEvent]]:
        started_at = (
            self._orchestrator._trace_sink.start()
            if self._orchestrator._trace_sink is not None
            else time.perf_counter()
        )
        state = await self._graph.ainvoke(
            {
                "session_id": session_id,
                "user_text": user_text,
                "correlation_id": correlation_id,
                "idempotency_key": idempotency_key,
                "events": [],
                "trace": [],
            },
            config={
                "configurable": {
                    "thread_id": f"{session_id}:{correlation_id}",
                }
            },
        )
        result = state["result"]
        if self._orchestrator._trace_sink is not None:
            trace_event = await self._orchestrator._trace_sink.publish(
                self._orchestrator._events,
                session_id=session_id,
                correlation_id=correlation_id,
                trace=state.get("trace", []),
                user_text=user_text,
                assistant_text=result[0].content if result and result[0] else "",
                started_at=started_at,
            )
            result = (result[0], result[1], result[2], [*result[3], trace_event])
        return result

    def _build_graph(self):
        graph = StateGraph(MultiResponseState)
        graph.add_node("record_user_message", self._record_user_message)
        graph.add_node("publish_agent_plan", self._publish_agent_plan)
        graph.add_node("classify_request", self._classify_request)
        graph.add_node("report_process_status", self._report_process_status)
        graph.add_node("report_simulation_status", self._report_simulation_status)
        graph.add_node("report_available_actions", self._report_available_actions)
        graph.add_node("report_run_comparison", self._report_run_comparison)
        graph.add_node("optimize_agv_count", self._optimize_agv_count)
        graph.add_node("retrieve", self._retrieve)
        graph.add_node("report_general_chat", self._report_general_chat)
        graph.add_node("resolve_station", self._resolve_station)
        graph.add_node("plan_tool_call", self._plan_tool_call)
        graph.add_node("finalize_robot_command", self._finalize_robot_command)

        graph.add_edge(START, "record_user_message")
        graph.add_edge("record_user_message", "publish_agent_plan")
        graph.add_edge("publish_agent_plan", "classify_request")
        graph.add_conditional_edges(
            "classify_request",
            self._next_route,
            {
                "process_status": "report_process_status",
                "simulation_status": "report_simulation_status",
                "station_action_query": "report_available_actions",
                "compare_runs": "report_run_comparison",
                "optimize_agvs": "optimize_agv_count",
                "knowledge_query": "retrieve",
                "general_chat": "retrieve",
                "robot_command": "resolve_station",
            },
        )
        graph.add_edge("report_process_status", END)
        graph.add_edge("report_simulation_status", END)
        graph.add_edge("report_available_actions", END)
        graph.add_edge("report_run_comparison", END)
        graph.add_edge("optimize_agv_count", END)
        graph.add_edge("retrieve", "report_general_chat")
        graph.add_edge("report_general_chat", END)
        graph.add_edge("resolve_station", "plan_tool_call")
        graph.add_conditional_edges(
            "plan_tool_call",
            self._tool_plan_route,
            {
                "finalize": "finalize_robot_command",
                "end": END,
            },
        )
        graph.add_edge("finalize_robot_command", END)
        return graph.compile(checkpointer=self._checkpointer)

    async def _record_user_message(self, state: MultiResponseState) -> dict[str, Any]:
        user_message = ChatMessage(
            session_id=state["session_id"],
            role=MessageRole.USER,
            content=state["user_text"],
            correlation_id=state["correlation_id"],
        )
        await self._orchestrator._repository.add_message(user_message)
        received = DomainEvent(
            event_type="chat.message.received",
            correlation_id=state["correlation_id"],
            session_id=state["session_id"],
            payload={"message_id": user_message.message_id},
        )
        await self._orchestrator._events.publish(received)
        return {
            "user_message": user_message,
            "events": [received],
            "trace": [{"node": "record_user_message"}],
        }

    async def _publish_agent_plan(self, state: MultiResponseState) -> dict[str, Any]:
        plan_events = await self._orchestrator._publish_agent_plan(
            session_id=state["session_id"],
            user_text=state["user_text"],
            correlation_id=state["correlation_id"],
        )
        return {
            "events": plan_events,
            "trace": [{"node": "publish_agent_plan", "event_count": len(plan_events)}],
        }

    async def _classify_request(self, state: MultiResponseState) -> dict[str, Any]:
        route, source = await self._orchestrator._classify_route(
            state["user_text"],
            state["correlation_id"],
        )
        selected = DomainEvent(
            event_type="agent.route.selected",
            correlation_id=state["correlation_id"],
            session_id=state["session_id"],
            payload={"route": route, "source": source},
        )
        await self._orchestrator._events.publish(selected)
        return {
            "route": route,
            "events": [selected],
            "trace": [{"node": "classify_request", "route": route, "source": source}],
        }

    async def _report_process_status(self, state: MultiResponseState) -> dict[str, Any]:
        telemetry = await self._orchestrator._iot_telemetry.get_process_telemetry(
            state["correlation_id"]
        )
        reported = DomainEvent(
            event_type="process.telemetry.reported",
            correlation_id=state["correlation_id"],
            session_id=state["session_id"],
            payload=telemetry.model_dump(mode="json"),
        )
        await self._orchestrator._events.publish(reported)
        assistant = await self._orchestrator._add_assistant_message(
            state["session_id"],
            self._orchestrator._process_status_message(telemetry),
            state["correlation_id"],
        )
        events = [*state["events"], reported]
        return {
            "assistant": assistant,
            "events": [reported],
            "trace": [{"node": "report_process_status"}],
            "result": (assistant, None, None, events),
        }

    async def _report_simulation_status(self, state: MultiResponseState) -> dict[str, Any]:
        hub = self._orchestrator._live_telemetry
        agvs = hub.agvs()
        process = hub.process()
        reported = DomainEvent(
            event_type="simulation.status.reported",
            correlation_id=state["correlation_id"],
            session_id=state["session_id"],
            payload={"agv_count": len(agvs), "agvs": agvs, "process": process},
        )
        await self._orchestrator._events.publish(reported)
        assistant = await self._orchestrator._add_assistant_message(
            state["session_id"],
            self._orchestrator._simulation_status_message(agvs, process),
            state["correlation_id"],
        )
        events = [*state["events"], reported]
        return {
            "assistant": assistant,
            "events": [reported],
            "trace": [{"node": "report_simulation_status", "agv_count": len(agvs)}],
            "result": (assistant, None, None, events),
        }

    async def _report_available_actions(self, state: MultiResponseState) -> dict[str, Any]:
        stations = await self._orchestrator._station_status_agent.list_stations(state["correlation_id"])
        assistant = await self._orchestrator._add_assistant_message(
            state["session_id"],
            self._orchestrator._available_actions_message(stations),
            state["correlation_id"],
        )
        return {
            "assistant": assistant,
            "trace": [{"node": "report_available_actions", "station_count": len(stations)}],
            "result": (assistant, None, None, state["events"]),
        }

    async def _report_run_comparison(self, state: MultiResponseState) -> dict[str, Any]:
        message = await self._orchestrator._compare_recent_runs(
            state["session_id"],
            state["correlation_id"],
        )
        assistant = await self._orchestrator._add_assistant_message(
            state["session_id"],
            message,
            state["correlation_id"],
        )
        return {
            "assistant": assistant,
            "trace": [{"node": "report_run_comparison"}],
            "result": (assistant, None, None, state["events"]),
        }

    async def _optimize_agv_count(self, state: MultiResponseState) -> dict[str, Any]:
        assistant = await self._orchestrator._run_agv_optimization(
            state["session_id"],
            state["user_text"],
            state["correlation_id"],
        )
        return {
            "assistant": assistant,
            "trace": [{"node": "optimize_agv_count"}],
            "result": (assistant, None, None, state["events"]),
        }

    async def _retrieve(self, state: MultiResponseState) -> dict[str, Any]:
        """Ground free-text Q&A: fetch knowledge-base chunks before the answer is written.

        A no-op when RAG is disabled (the orchestrator returns []), so the general-chat path
        is unchanged in the default demo configuration.
        """
        chunks, event = await self._orchestrator._retrieve_knowledge(
            state["user_text"],
            state["session_id"],
            state["correlation_id"],
        )
        out: dict[str, Any] = {
            "retrieved": chunks,
            "trace": [{"node": "retrieve", "hits": len(chunks)}],
        }
        if event is not None:
            out["events"] = [event]
        return out

    async def _report_general_chat(self, state: MultiResponseState) -> dict[str, Any]:
        message = await self._orchestrator._general_chat_message(
            state["user_text"],
            state["session_id"],
            state["correlation_id"],
            knowledge=state.get("retrieved"),
        )
        assistant = await self._orchestrator._add_assistant_message(
            state["session_id"],
            message,
            state["correlation_id"],
        )
        return {
            "assistant": assistant,
            "trace": [{"node": "report_general_chat"}],
            "result": (assistant, None, None, state["events"]),
        }

    async def _resolve_station(self, state: MultiResponseState) -> dict[str, Station | None]:
        station = await self._orchestrator._station_status_agent.resolve_station(
            state["user_text"],
            state["correlation_id"],
        )
        return {
            "station": station,
            "trace": [
                {
                    "node": "resolve_station",
                    "station_id": station.station_id if station else None,
                }
            ],
        }

    async def _plan_tool_call(self, state: MultiResponseState) -> dict[str, Any]:
        try:
            validated_tool_call = await self._orchestrator._robot_control_agent.plan_tool_call(
                state["user_text"],
                state.get("station"),
                state["correlation_id"],
            )
        except ToolValidationError as exc:
            assistant = await self._orchestrator._add_assistant_message(
                state["session_id"],
                self._orchestrator._failure_policy.invalid_tool_message(exc),
                state["correlation_id"],
            )
            return {
                "assistant": assistant,
                "route": "end",
                "status": CommandStatus.PENDING_CONFIRMATION,
                "trace": [{"node": "plan_tool_call", "error": "invalid_tool"}],
                "result": (
                    assistant,
                    None,
                    CommandStatus.PENDING_CONFIRMATION,
                    state["events"],
                ),
            }
        except LlmGatewayError:
            assistant = await self._orchestrator._add_assistant_message(
                state["session_id"],
                self._orchestrator._failure_policy.llm_unavailable_message(),
                state["correlation_id"],
            )
            return {
                "assistant": assistant,
                "route": "end",
                "status": CommandStatus.PENDING_CONFIRMATION,
                "trace": [{"node": "plan_tool_call", "error": "llm_unavailable"}],
                "result": (
                    assistant,
                    None,
                    CommandStatus.PENDING_CONFIRMATION,
                    state["events"],
                ),
            }
        return {
            "validated_tool_call": validated_tool_call,
            "route": "finalize",
            "trace": [
                {
                    "node": "plan_tool_call",
                    "tool": validated_tool_call.name.value if validated_tool_call else None,
                }
            ],
        }

    async def _finalize_robot_command(self, state: MultiResponseState) -> dict[str, Any]:
        validated_tool_call = state.get("validated_tool_call")
        if validated_tool_call is None:
            validated_tool_call = self._orchestrator._consume_pending_confirmation(
                state["session_id"],
                state["user_text"],
            )
        if validated_tool_call is None:
            cancel_call = await self._build_cancel_tool_call(state)
            if cancel_call is None:
                if self._orchestrator._is_cancel_request(state["user_text"]):
                    assistant = await self._orchestrator._add_assistant_message(
                        state["session_id"],
                        "취소할 진행 중인 AGV 작업을 찾지 못했습니다.",
                        state["correlation_id"],
                    )
                    return {
                        "assistant": assistant,
                        "trace": [{"node": "finalize_robot_command", "status": "cancel_not_found"}],
                        "result": (assistant, None, None, state["events"]),
                    }
                assistant = await self._orchestrator._add_assistant_message(
                    state["session_id"],
                    self._orchestrator._failure_policy.ambiguous_command_message(),
                    state["correlation_id"],
                )
                return {
                    "assistant": assistant,
                    "trace": [{"node": "finalize_robot_command", "status": "ambiguous"}],
                    "result": (assistant, None, None, state["events"]),
                }
            validated_tool_call = cancel_call

        if (
            validated_tool_call.name == RobotCommandName.START_SIMULATION
            and "agv_count" not in validated_tool_call.arguments
        ):
            # No count specified → run the cell at capacity: the max AGV count read live from UE5
            # (falls back to the configured fleet size). Keeps a plain "start" from defaulting to 3.
            validated_tool_call.arguments["agv_count"] = (
                await self._orchestrator._resolve_max_agv_count(state["correlation_id"])
            )

        proposed = DomainEvent(
            event_type="llm.tool_call.proposed",
            correlation_id=state["correlation_id"],
            session_id=state["session_id"],
            payload={
                "tool_name": validated_tool_call.name,
                "arguments": validated_tool_call.arguments,
            },
        )
        await self._orchestrator._events.publish(proposed)
        events = [*state["events"], proposed]
        station = state.get("station")

        confirmation = await self._orchestrator._safety_confirmation_required(
            state["session_id"],
            state["user_text"],
            validated_tool_call,
            state["correlation_id"],
        )
        if confirmation is not None:
            assistant = await self._orchestrator._add_assistant_message(
                session_id=state["session_id"],
                content=confirmation,
                correlation_id=state["correlation_id"],
            )
            return {
                "assistant": assistant,
                "events": [proposed],
                "trace": [{"node": "finalize_robot_command", "status": "pending_safety"}],
                "result": (assistant, None, CommandStatus.PENDING_CONFIRMATION, events),
            }

        if station and not station.task_ready and validated_tool_call.name == RobotCommandName.RUN_STATION_TASK:
            assistant = await self._orchestrator._add_assistant_message(
                session_id=state["session_id"],
                content=self._orchestrator._station_task_blocked_message(station),
                correlation_id=state["correlation_id"],
            )
            return {
                "assistant": assistant,
                "events": [proposed],
                "trace": [{"node": "finalize_robot_command", "status": "station_not_ready"}],
                "result": (assistant, None, CommandStatus.PENDING_CONFIRMATION, events),
            }

        if station and not station.accessible and validated_tool_call.name in {
            RobotCommandName.RUN_STATION_TASK,
            RobotCommandName.MOVE_TO_STATION,
        }:
            assistant = await self._orchestrator._add_assistant_message(
                session_id=state["session_id"],
                content=(
                    f"{station.station_id}번 스테이션은 작업 준비는 됐지만 현재 AGV 접근 경로가 막혀 있어 "
                    "이동/작업 명령을 발행하지 않았습니다. 먼저 스테이션 점검 또는 작업자 접근 경로 확인이 필요합니다."
                ),
                correlation_id=state["correlation_id"],
            )
            return {
                "assistant": assistant,
                "events": [proposed],
                "trace": [{"node": "finalize_robot_command", "status": "station_inaccessible"}],
                "result": (assistant, None, CommandStatus.PENDING_CONFIRMATION, events),
            }

        command = await self._orchestrator._robot_commands.issue_robot_command(
            session_id=state["session_id"],
            command_name=validated_tool_call.name,
            parameters=validated_tool_call.arguments,
            correlation_id=state["correlation_id"],
            idempotency_key=state["idempotency_key"],
        )
        if command.status == CommandStatus.FAILED:
            # UE5 never received the command — surface the failure instead of mirroring a
            # phantom run into the simulation store and reporting success.
            assistant = await self._orchestrator._add_assistant_message(
                session_id=state["session_id"],
                content=self._orchestrator._command_dispatch_failed_message(
                    validated_tool_call.name
                ),
                correlation_id=state["correlation_id"],
            )
            return {
                "assistant": assistant,
                "command": command,
                "command_id": command.command_id,
                "status": command.status,
                "events": [proposed],
                "trace": [{"node": "finalize_robot_command", "status": "dispatch_failed"}],
                "result": (assistant, command.command_id, command.status, events),
            }
        lifecycle_events = await self._orchestrator._sync_simulation_lifecycle(command)
        events = [*events, *lifecycle_events]
        # Extract the run_id created by _sync_simulation_lifecycle so START_SIMULATION
        # can include it in the confirmation message.
        run_id: str | None = next(
            (
                ev.payload.get("run_id")
                for ev in lifecycle_events
                if ev.event_type == "simulation.created" and isinstance(ev.payload.get("run_id"), str)
            ),
            None,
        )
        assistant = ChatMessage(
            session_id=state["session_id"],
            role=MessageRole.ASSISTANT,
            content=self._orchestrator._sanitize_output(
                self._orchestrator._accepted_message(
                    validated_tool_call.name,
                    validated_tool_call.arguments,
                    command.command_id,
                    run_id=run_id,
                )
            ),
            correlation_id=state["correlation_id"],
        )
        await self._orchestrator._repository.add_message(assistant)
        if self._orchestrator._auto_complete_commands:
            assistant, auto_events = await self._orchestrator._complete_demo_command(command)
            completed_events = [*events, *auto_events]
            return {
                "assistant": assistant,
                "command": command,
                "command_id": command.command_id,
                "status": CommandStatus.COMPLETED,
                "events": [proposed, *lifecycle_events, *auto_events],
                "trace": [{"node": "finalize_robot_command", "status": "completed"}],
                "result": (
                    assistant,
                    command.command_id,
                    CommandStatus.COMPLETED,
                    completed_events,
                ),
            }
        return {
            "assistant": assistant,
            "command": command,
            "command_id": command.command_id,
            "status": command.status,
            "events": [proposed, *lifecycle_events],
            "trace": [{"node": "finalize_robot_command", "status": command.status.value}],
            "result": (assistant, command.command_id, command.status, events),
        }

    async def _build_cancel_tool_call(
        self,
        state: MultiResponseState,
    ) -> ValidatedToolCall | None:
        if not self._orchestrator._is_cancel_request(state["user_text"]):
            return None
        latest_command = await self._orchestrator._latest_cancelable_command(state["session_id"])
        if latest_command is None:
            return None
        return self._orchestrator._tool_router.validate(
            ToolCall(
                name=RobotCommandName.CANCEL_COMMAND,
                arguments={"command_id": latest_command.command_id},
            )
        )

    def _next_route(self, state: MultiResponseState) -> str:
        return state["route"]

    def _tool_plan_route(self, state: MultiResponseState) -> str:
        return state["route"]
