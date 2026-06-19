from __future__ import annotations

import asyncio
import re

from app.agents.failure_policy import AgentFailurePolicy, LlmGatewayError
from app.agents.optimization_agent import OptimizationAgent
from app.agents.planning_agent import PlanningAgent
from app.agents.report_agent import ReportAgent
from app.agents.robot_control_agent import RobotControlAgent
from app.agents.station_status_agent import StationStatusAgent
from app.application.live_telemetry import LiveTelemetryHub
from app.application.multi_response_graph import LangGraphMultiResponseAgent
from app.application.ports import (
    ControlServerClient,
    EventPublisher,
    IotTelemetryClient,
    KnowledgeGateway,
    LlmGateway,
    SessionRepository,
)
from app.application.robot_orchestrator import RobotCommandOrchestrator
from app.domain.evaluation import ComparedRun, RunComparison, build_run_comparison
from app.domain.optimization import (
    OptimizationGoal,
    OptimizationOutcome,
    OptimizationStep,
    goal_satisfied,
    is_optimize_request,
)
from app.domain.process_model import bottleneck_rate_from_heatmap
from app.domain.models import (
    SIM_LIFECYCLE_COMMANDS,
    ChatMessage,
    CommandStatus,
    DomainEvent,
    MessageRole,
    ProcessTelemetry,
    RetrievedChunk,
    RobotCommand,
    RobotCommandName,
    SimulationRun,
    SimulationRunStatus,
    Simulation,
    utc_now,
)
from app.tools.contracts import ValidatedToolCall
from app.tools.router import ToolRouter

# Per-candidate run length and the max wall-clock wait for its KPIs in the live optimization
# loop. Kept short so a 1–3 run search finishes in a demo-friendly time. TODO: config.
_OPTIMIZE_RUN_DURATION_SEC = 60
_OPTIMIZE_RUN_TIMEOUT_SEC = 300.0

# Deterministic plans for cheaply-detectable simple intents. These rote control commands don't
# need an LLM round-trip — routing them through the small local model produced padded, repetitive
# steps that leaked internal route identifiers (e.g. "command_cancel ... 재시도"). Keeping them
# fixed makes the plan length track task complexity (2 steps to stop, 5 to search), which is what
# a visible plan should show. The optimize plan is templated on the *parsed* goal threshold so the
# steps reflect the actual request (e.g. "병목률 25% 이하") rather than generic boilerplate.
# Genuinely variable requests (station tasks, free chat) still get an LLM-judged plan.
def _optimize_plan_steps(user_text: str) -> list[str]:
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", user_text)
    target = f"병목률 {match.group(1)}% 이하" if match else "목표 병목률 기준"
    return [
        f"요청을 'AGV 최적 대수 탐색' 목표({target})로 분류합니다.",
        "UE5 셀에 배치된 최대 AGV 대수를 조회해 탐색 상한으로 사용합니다.",
        f"최대 대수부터 한 대씩 줄여가며 각 후보를 시뮬레이션하고 {target} 만족 여부를 측정합니다.",
        f"{target}를 만족하는 최대 AGV 대수를 결정합니다.",
        "후보별 KPI와 최적 결과를 보고서로 정리해 전달합니다.",
    ]
_CANCEL_PLAN_STEPS = [
    "요청을 진행 중인 AGV 작업 취소로 분류합니다.",
    "가장 최근의 취소 가능한 명령을 찾아 취소 명령을 UE5 공정에 전달합니다.",
]
_SIM_CONTROL_PLAN_STEPS = [
    "요청을 시뮬레이션 제어(정지·일시정지·재개·속도) 명령으로 분류합니다.",
    "해당 제어 명령을 검증해 UE5 가상 공정에 전달합니다.",
]
_SIM_START_PLAN_STEPS = [
    "요청에서 AGV 대수와 합격 기준(목표 KPI)을 추출합니다.",
    "시작 명령 인자를 스키마로 검증합니다.",
    "UE5 가상 공정에 AGV를 배치해 시뮬레이션을 시작하고 진행 이벤트를 추적합니다.",
]
# Verbs that mark a *start* request among explicit sim-lifecycle commands; the stop verbs take
# precedence so "다시 시작" reads as start but "정지/속도" never does.
_SIM_START_VERBS = (
    "시작", "돌려", "돌리", "돌린", "돌립", "배치", "투입", "실행", "가동",
    "start", "run", "launch", "deploy",
)
_SIM_STOP_VERBS = (
    "정지", "중단", "멈춰", "일시정지", "재개", "속도", "배속",
    "stop", "pause", "resume", "speed",
)


class _RunFailedError(Exception):
    """Raised inside the live optimization loop when a candidate run reports failure."""


class ChatOrchestrator:
    def __init__(
        self,
        repository: SessionRepository,
        control_client: ControlServerClient,
        iot_telemetry: IotTelemetryClient,
        llm: LlmGateway,
        robot_commands: RobotCommandOrchestrator,
        events: EventPublisher,
        tool_router: ToolRouter | None = None,
        station_status_agent: StationStatusAgent | None = None,
        robot_control_agent: RobotControlAgent | None = None,
        planning_agent: PlanningAgent | None = None,
        report_agent: ReportAgent | None = None,
        failure_policy: AgentFailurePolicy | None = None,
        auto_complete_commands: bool = False,
        agv_fleet_max: int = 5,
        live_telemetry: LiveTelemetryHub | None = None,
        knowledge: KnowledgeGateway | None = None,
        rag_top_k: int = 5,
    ) -> None:
        self._repository = repository
        self._control_client = control_client
        self._iot_telemetry = iot_telemetry
        self._llm = llm
        self._robot_commands = robot_commands
        self._events = events
        self._tool_router = tool_router or ToolRouter()
        self._station_status_agent = station_status_agent or StationStatusAgent(control_client)
        self._robot_control_agent = robot_control_agent or RobotControlAgent(
            llm,
            self._tool_router,
        )
        self._planning_agent = planning_agent or PlanningAgent()
        self._optimization_agent = OptimizationAgent()
        self._report_agent = report_agent or ReportAgent(llm)
        self._failure_policy = failure_policy or AgentFailurePolicy()
        self._auto_complete_commands = auto_complete_commands
        # Fallback cell fleet size; the live value is read from UE5 /sim/status per request.
        self._agv_fleet_max = agv_fleet_max
        # Live per-AGV / process frames cached from the UE5 WebSocket stream, used to answer
        # mid-run "current status" questions with per-AGV state + collisions (not just KPIs).
        self._live_telemetry = live_telemetry or LiveTelemetryHub()
        # RAG knowledge retrieval (spec_rag.md §5). None = retrieval disabled (no grounding),
        # so the demo runs ungrounded when RAG_ENABLED is off; the container injects the
        # Qdrant gateway when RAG is on (the Null gateway covers the "enabled but down" case).
        self._knowledge = knowledge
        self._rag_top_k = rag_top_k
        self._pending_confirmations: dict[str, ValidatedToolCall] = {}
        # Long-running optimization searches drive the live UE5 loop across many real runs, which
        # outlives a single chat turn. Keep strong refs so the tasks aren't GC'd mid-flight.
        self._background_tasks: set[asyncio.Task] = set()
        self._multi_response_agent = LangGraphMultiResponseAgent(self)

    async def handle_user_message(
        self,
        session_id: str,
        user_text: str,
        correlation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[ChatMessage, str | None, CommandStatus | None, list[DomainEvent]]:
        from app.domain.models import new_id

        correlation_id = correlation_id or new_id("corr")
        idempotency_key = idempotency_key or f"{session_id}:{correlation_id}"
        return await self._multi_response_agent.handle(
            session_id=session_id,
            user_text=user_text,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
        )

    async def handle_completion_event(self, event: DomainEvent) -> ChatMessage:
        command = await self._repository.get_command(event.command_id or "")
        if command is None:
            raise ValueError(f"Unknown command for completion event: {event.command_id}")
        command.status = (
            CommandStatus.COMPLETED
            if event.event_type == "robot.command.completed"
            else CommandStatus.FAILED
        )
        await self._repository.update_command(command)
        await self._events.publish(event)

        if (
            command.command_name == RobotCommandName.START_SIMULATION
            and command.parameters.get("suppress_completion_report") is True
        ):
            return ChatMessage(
                session_id=event.session_id,
                role=MessageRole.ASSISTANT,
                content="",
                correlation_id=event.correlation_id,
            )

        # Pause / resume / speed are lifecycle ACKs — they don't end the simulation
        # and don't need a KPI report. Return a brief status line instead.
        if command.command_name in {
            RobotCommandName.PAUSE_SIMULATION,
            RobotCommandName.RESUME_SIMULATION,
            RobotCommandName.SET_SIM_SPEED,
        }:
            if command.command_name == RobotCommandName.PAUSE_SIMULATION:
                content = "시뮬레이션이 일시정지되었습니다. '재개해줘'로 계속할 수 있습니다."
            elif command.command_name == RobotCommandName.RESUME_SIMULATION:
                content = "시뮬레이션이 재개되었습니다."
            else:
                speed = command.parameters.get("speed_multiplier")
                content = f"시뮬레이션 속도가 {speed}배로 변경되었습니다." if speed else "시뮬레이션 속도가 변경되었습니다."
            ack = ChatMessage(
                session_id=event.session_id,
                role=MessageRole.ASSISTANT,
                content=content,
                correlation_id=event.correlation_id,
            )
            await self._repository.add_message(ack)
            return ack

        await self._events.publish(
            DomainEvent(
                event_type="chat.report.generating",
                correlation_id=event.correlation_id,
                session_id=event.session_id,
                command_id=event.command_id,
                payload={"status": "generating"},
            )
        )
        knowledge, _ = await self._retrieve_knowledge(
            self._report_retrieval_query(event, command),
            event.session_id,
            event.correlation_id,
        )
        report = await self._report_agent.generate_report(
            event, command, event.correlation_id, knowledge=knowledge
        )
        message = ChatMessage(
            session_id=event.session_id,
            role=MessageRole.ASSISTANT,
            content=report,
            correlation_id=event.correlation_id,
        )
        await self._repository.add_message(message)
        # Forward the structured KPIs/verdict (present on a simulation-run completion) so the
        # web overlay can render per-item KPI and pass/fail cards alongside the LLM narrative.
        report_payload: dict = {"message_id": message.message_id, "content": message.content}
        kpis = event.payload.get("kpis")
        if isinstance(kpis, dict):
            report_payload["kpis"] = kpis
        verdict = event.payload.get("verdict")
        if isinstance(verdict, dict):
            report_payload["verdict"] = verdict
        await self._events.publish(
            DomainEvent(
                event_type="chat.report.generated",
                correlation_id=event.correlation_id,
                session_id=event.session_id,
                command_id=event.command_id,
                payload=report_payload,
            )
        )
        return message

    async def _add_assistant_message(
        self,
        session_id: str,
        content: str,
        correlation_id: str,
    ) -> ChatMessage:
        assistant = ChatMessage(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=content,
            correlation_id=correlation_id,
        )
        await self._repository.add_message(assistant)
        return assistant

    async def _retrieve_knowledge(
        self,
        query: str,
        session_id: str,
        correlation_id: str,
    ) -> tuple[list[RetrievedChunk], DomainEvent | None]:
        """Retrieve grounding chunks and publish an ``agent.retrieval`` event when there are hits.

        Returns ``([], None)`` when RAG is disabled (no gateway injected) or retrieval yields
        nothing, so callers can treat grounding as best-effort. Retrieval failures inside the
        gateway are already swallowed to [] there — the demo never hard-fails on a degraded
        store. The published event is also returned so the graph can accumulate it into the
        response (the report path, which only feeds the live bus, ignores it).
        """
        if self._knowledge is None or not query.strip():
            return [], None
        chunks = await self._knowledge.retrieve(
            query, correlation_id, top_k=self._rag_top_k
        )
        # Only surface retrieval that found something. An empty result (RAG disabled via the
        # Null gateway, or an honest miss) carries no grounding for the overlay to show.
        if not chunks:
            return [], None
        event = DomainEvent(
            event_type="agent.retrieval",
            correlation_id=correlation_id,
            session_id=session_id,
            payload={
                "query": query,
                "hits": [
                    {
                        "document_id": chunk.document_id,
                        "title": chunk.title,
                        "score": chunk.score,
                    }
                    for chunk in chunks
                ],
            },
        )
        await self._events.publish(event)
        return chunks, event

    def _report_retrieval_query(self, event: DomainEvent, command: RobotCommand) -> str:
        """Build a retrieval query for a run report, biased toward the concerning KPIs.

        A bare command name retrieves little; surfacing the metrics that look bad (collisions,
        bottlenecks, low throughput) pulls the matching SOP/playbook so the verdict is grounded.
        """
        parts = ["AGV 가상 공정 시뮬레이션 결과 분석"]
        kpis = event.payload.get("kpis")
        if isinstance(kpis, dict):
            def _num(value: object) -> float | None:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return None
                return float(value)

            collisions = _num(kpis.get("collisions")) or _num(kpis.get("collision_risk"))
            if collisions:
                parts.append("AGV 충돌 위험 대응 절차")
            if _num(kpis.get("bottleneck_rate")):
                parts.append("병목 구간 처리량 개선")
            throughput = _num(kpis.get("throughput"))
            if throughput is not None and throughput < 1.0:
                parts.append("처리량 저하 원인")
            if _num(kpis.get("avg_wait_time")):
                parts.append("대기 시간 단축")
        return " ".join(parts)

    async def _complete_demo_command(self, command: RobotCommand) -> tuple[ChatMessage, list[DomainEvent]]:
        events: list[DomainEvent] = []
        station_id = command.parameters.get("station_id")

        if command.command_name in {
            RobotCommandName.RUN_STATION_TASK,
            RobotCommandName.MOVE_TO_STATION,
        }:
            moving = DomainEvent(
                event_type="robot.moving",
                correlation_id=command.correlation_id,
                session_id=command.session_id,
                command_id=command.command_id,
                payload={"robot_id": "agv_demo_1", "target_station_id": station_id},
            )
            await self._events.publish(moving)
            events.append(moving)

        if command.command_name == RobotCommandName.RUN_STATION_TASK:
            working = DomainEvent(
                event_type="robot.working",
                correlation_id=command.correlation_id,
                session_id=command.session_id,
                command_id=command.command_id,
                payload={"robot_id": "agv_demo_1", "station_id": station_id},
            )
            await self._events.publish(working)
            events.append(working)

        completed = DomainEvent(
            event_type="robot.command.completed",
            correlation_id=command.correlation_id,
            session_id=command.session_id,
            command_id=command.command_id,
            payload={"robot_id": "agv_demo_1", "station_id": station_id},
        )
        message = await self.handle_completion_event(completed)
        events.append(completed)
        return message, events

    async def _sync_simulation_lifecycle(self, command: RobotCommand) -> list[DomainEvent]:
        """Mirror a chat-driven simulation command into the simulation/run store.

        A simulation the operator launches from chat must show up in the simulation list
        side tab (and its run history) exactly like a manually-authored one, and a chat
        stop/pause/resume/speed command must drive whatever run is currently live —
        regardless of whether it was started from chat or the simulation panel. The emitted
        events let the web overlay refresh that list without a poll.
        """
        if command.command_name not in SIM_LIFECYCLE_COMMANDS:
            return []
        events: list[DomainEvent] = []
        if command.command_name == RobotCommandName.START_SIMULATION:
            simulation = await self._create_chat_simulation(command.parameters)
            run = await self._repository.create_run(
                SimulationRun(
                    simulation_id=simulation.simulation_id,
                    status=SimulationRunStatus.RUNNING,
                    speed_multiplier=simulation.speed_multiplier,
                    started_at=utc_now(),
                    ue_run_id=command.command_id,
                )
            )
            events.append(
                self._simulation_lifecycle_event(
                    "simulation.created",
                    command,
                    {
                        "simulation_id": simulation.simulation_id,
                        "name": simulation.name,
                        "run_id": run.run_id,
                        "status": run.status,
                        "source": "chat",
                    },
                )
            )
        else:
            run = await self._latest_active_run()
            if run is None:
                return []
            if command.command_name == RobotCommandName.STOP_SIMULATION:
                run.status = SimulationRunStatus.STOPPED
                run.ended_at = utc_now()
            elif command.command_name == RobotCommandName.PAUSE_SIMULATION:
                run.status = SimulationRunStatus.PAUSED
            elif command.command_name == RobotCommandName.RESUME_SIMULATION:
                run.status = SimulationRunStatus.RUNNING
            elif command.command_name == RobotCommandName.SET_SIM_SPEED:
                speed = command.parameters.get("speed_multiplier")
                if isinstance(speed, (int, float)):
                    run.speed_multiplier = float(speed)
            await self._repository.update_run(run)
            events.append(
                self._simulation_lifecycle_event(
                    "simulation.run.updated",
                    command,
                    {
                        "simulation_id": run.simulation_id,
                        "run_id": run.run_id,
                        "status": run.status,
                        "speed_multiplier": run.speed_multiplier,
                        "source": "chat",
                    },
                )
            )
        for event in events:
            await self._events.publish(event)
        return events

    async def _create_chat_simulation(self, parameters: dict) -> Simulation:
        def _num(key: str, default: float) -> float:
            value = parameters.get(key)
            return float(value) if isinstance(value, (int, float)) else default

        agv_count = int(_num("agv_count", 3))
        speed = _num("speed_multiplier", 1.0)
        duration = parameters.get("duration", parameters.get("duration_seconds"))
        duration_seconds = int(duration) if isinstance(duration, (int, float)) else 600
        label = utc_now().strftime("%m-%d %H:%M")
        simulation = Simulation(
            name=f"챗봇 시뮬레이션 · AGV {agv_count}대 ({label})",
            agv_count=agv_count,
            speed_multiplier=speed,
            workload_percent=_num("workload_percent", 100.0),
            policy_id=str(parameters.get("policy_id") or "POLICY_FIFO"),
            duration_seconds=duration_seconds,
            bottleneck_threshold_sec=_num("bottleneck_threshold_sec", 10.0),
        )
        return await self._repository.create_simulation(simulation)

    async def _latest_active_run(self) -> SimulationRun | None:
        active = {
            SimulationRunStatus.STARTING,
            SimulationRunStatus.RUNNING,
            SimulationRunStatus.PAUSED,
        }
        # list_runs() is ordered newest-first, so the first active run is the live one.
        for run in await self._repository.list_runs():
            if run.status in active:
                return run
        return None

    async def _compare_recent_runs(self, session_id: str, correlation_id: str) -> str:
        """Compare the two most recent runs that have final KPIs into a graded A/B verdict."""
        runs = await self._repository.list_runs()  # newest-first
        finished = [run for run in runs if isinstance(run.kpis_json, dict) and run.kpis_json][:2]
        if len(finished) < 2:
            return (
                "비교하려면 KPI가 집계된 완료 실행이 2개 이상 필요합니다. "
                "수용 기준을 건 시뮬레이션을 두 번 돌린 뒤 다시 요청해 주세요."
            )
        newer, older = finished[0], finished[1]
        older_label = await self._run_compare_label(older)
        newer_label = await self._run_compare_label(newer)
        if older_label == newer_label:  # identical params → disambiguate by recency
            older_label += " (이전)"
            newer_label += " (최근)"

        def _verdict(run) -> dict | None:
            return run.result_json.get("verdict") if isinstance(run.result_json, dict) else None

        comparison = build_run_comparison(
            ComparedRun(label=older_label, kpis=older.kpis_json or {}, verdict=_verdict(older)),
            ComparedRun(label=newer_label, kpis=newer.kpis_json or {}, verdict=_verdict(newer)),
        )
        if comparison is None:
            return "두 실행의 공통 KPI가 부족해 비교할 수 없습니다."
        await self._events.publish(
            DomainEvent(
                event_type="agent.run.comparison",
                correlation_id=correlation_id,
                session_id=session_id,
                payload={
                    "winner": comparison.winner_label,
                    "runs": [
                        {"run_id": older.run_id, "label": older_label},
                        {"run_id": newer.run_id, "label": newer_label},
                    ],
                },
            )
        )
        return self._run_comparison_message(comparison)

    async def _run_compare_label(self, run) -> str:
        simulation = await self._repository.get_simulation(run.simulation_id)
        short_id = run.run_id[-6:]
        if simulation is not None:
            return f"AGV {simulation.agv_count}대·{simulation.speed_multiplier:g}배속 (#{short_id})"
        return f"실행 #{short_id}"

    def _run_comparison_message(self, comparison: RunComparison) -> str:
        lines = ["최근 두 시뮬레이션 실행 비교 결과입니다."]
        lines.extend(f"- {line.text}" for line in comparison.lines)
        lines.append(f"종합: {comparison.headline}")
        return "\n".join(lines)

    async def _resolve_max_agv_count(self, correlation_id: str) -> int:
        """Read the cell's maximum (authored) AGV count live from UE5.

        Queries /sim/status via the telemetry client and uses its ``max_agvs`` field as the
        optimizer's search upper bound. Falls back to the configured fleet size if UE5 is
        unreachable or doesn't report it, so the search never depends on a hardcoded constant.
        """
        try:
            telemetry = await self._iot_telemetry.get_process_telemetry(correlation_id)
        except Exception:  # telemetry boundary: never fail the turn on a status read.
            return self._agv_fleet_max
        if telemetry.max_agvs and telemetry.max_agvs > 0:
            return telemetry.max_agvs
        return self._agv_fleet_max

    async def _run_agv_optimization(
        self,
        session_id: str,
        user_text: str,
        correlation_id: str,
    ) -> ChatMessage:
        """Dispatch the goal-seeking AGV search to the live UE5 loop or the offline model.

        With UE5 live (``auto_complete_commands`` off) the search runs each candidate as a *real*
        simulation: it issues ``start_simulation`` to UE5, awaits the real completion KPIs, and
        decides the next candidate — a long-running job, so it runs in the background and the chat
        turn returns an immediate acknowledgement while progress streams as events. In mock/demo
        mode (no UE5) it falls back to the deterministic analytical model so the demo still works.
        """
        max_agvs = await self._resolve_max_agv_count(correlation_id)
        goal = self._optimization_agent.parse_goal(user_text, max_count=max_agvs)
        if goal is None:
            return await self._add_assistant_message(
                session_id,
                "최적화 목표를 이해하지 못했습니다. 예: '병목률 30% 이하를 만족하는 최적 AGV 대수를 찾아줘'.",
                correlation_id,
            )

        if self._auto_complete_commands:
            return await self._run_agv_optimization_model(session_id, correlation_id, goal)

        task = asyncio.create_task(
            self._run_agv_optimization_live(session_id, correlation_id, goal)
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return await self._add_assistant_message(
            session_id,
            self._optimization_started_message(goal),
            correlation_id,
        )

    def _optimization_step_message(
        self,
        goal: OptimizationGoal,
        step: OptimizationStep,
        next_count: int | None,
    ) -> str:
        """Narrate one observed candidate: its KPIs and the decision to stop or step down.

        Published as a chat message after each run completes (before the next run starts) so the
        operator sees *why* the search proceeds to the next AGV count rather than only the final
        verdict.
        """
        kpis = step.kpis
        head = f"AGV {step.agv_count}대 시뮬레이션 완료 → 병목률 {step.metric_value:.1f}% (목표: {goal.label})"
        detail = (
            f"처리량 {kpis.get('throughput', 0):.1f}/h · "
            f"평균대기 {kpis.get('avg_wait_time', 0):.1f}s · "
            f"충돌위험 {kpis.get('collision_risk', 0):.2f}/h · "
            f"가동률 {float(kpis.get('uptime', 0)) * 100:.0f}%"
        )
        if step.satisfied:
            verdict = f"{goal.label} 기준을 만족합니다. ✅ AGV {step.agv_count}대를 최적 후보로 확정하고 탐색을 종료합니다."
        elif next_count is not None:
            verdict = (
                f"{goal.label} 기준을 충족하지 못했습니다. "
                f"AGV를 한 대 줄여 {next_count}대로 다시 시뮬레이션합니다."
            )
        else:
            verdict = f"{goal.label} 기준을 충족하지 못했고 더 줄일 대수가 없어 탐색을 종료합니다."
        return f"{head}\n{detail}\n{verdict}"

    def _next_search_count(self, goal: OptimizationGoal, count: int, satisfied: bool) -> int | None:
        if satisfied:
            return None
        nxt = count - 1
        return nxt if nxt >= goal.min_count else None

    def _optimization_started_message(self, goal: OptimizationGoal) -> str:
        return (
            f"AGV 최적 대수 탐색을 시작합니다. (목표: {goal.label})\n"
            f"AGV {goal.max_count}대부터 한 대씩 줄여가며 실제 시뮬레이션을 실행하고 병목률을 "
            "측정합니다. 각 후보의 실행 결과가 순서대로 표시되고, 목표를 만족하는 최대 대수를 찾으면 "
            "최종 보고서를 전달합니다."
        )

    async def _run_agv_optimization_model(
        self,
        session_id: str,
        correlation_id: str,
        goal: OptimizationGoal,
    ) -> ChatMessage:
        """Offline fallback: search over the deterministic process model (no live UE5).

        Each candidate is persisted as a synthetic completed run and narrated as an event, so the
        multi-step reasoning stays visible even when UE5 is not running.
        """
        await self._events.publish(
            DomainEvent(
                event_type="agent.optimize.started",
                correlation_id=correlation_id,
                session_id=session_id,
                payload={
                    "goal": goal.label,
                    "metric": goal.metric,
                    "comparator": goal.comparator,
                    "threshold": goal.threshold,
                    "max_count": goal.max_count,
                    "min_count": goal.min_count,
                },
            )
        )

        outcome = self._optimization_agent.search(goal)

        for index, step in enumerate(outcome.steps, start=1):
            run = await self._persist_optimization_run(session_id, correlation_id, goal, step)
            await self._events.publish(
                DomainEvent(
                    event_type="agent.optimize.iteration",
                    correlation_id=correlation_id,
                    session_id=session_id,
                    payload={
                        "index": index,
                        "total_tried": len(outcome.steps),
                        "agv_count": step.agv_count,
                        "metric": goal.metric,
                        "metric_value": step.metric_value,
                        "satisfied": step.satisfied,
                        "run_id": run.run_id,
                        "kpis": step.kpis,
                    },
                )
            )
            # Narrate each candidate's result and the step-down decision as a chat message, in
            # order, so the reasoning is visible (not just the final report).
            await self._publish_optimization_report(
                session_id,
                correlation_id,
                self._optimization_step_message(
                    goal, step, self._next_search_count(goal, step.agv_count, step.satisfied)
                ),
                step.kpis,
            )

        await self._events.publish(
            DomainEvent(
                event_type="agent.optimize.completed",
                correlation_id=correlation_id,
                session_id=session_id,
                payload={
                    "goal": goal.label,
                    "optimal_count": outcome.optimal_count,
                    "tried_counts": [step.agv_count for step in outcome.steps],
                },
            )
        )

        return await self._add_assistant_message(
            session_id,
            self._optimization_report_message(outcome),
            correlation_id,
        )

    async def _persist_optimization_run(
        self,
        session_id: str,
        correlation_id: str,
        goal: OptimizationGoal,
        step,
    ) -> SimulationRun:
        """Record one optimization candidate as a completed run, mirrored to the run list."""
        label = utc_now().strftime("%m-%d %H:%M")
        simulation = await self._repository.create_simulation(
            Simulation(
                name=f"최적화 탐색 · AGV {step.agv_count}대 ({label})",
                agv_count=step.agv_count,
            )
        )
        now = utc_now()
        run = await self._repository.create_run(
            SimulationRun(
                simulation_id=simulation.simulation_id,
                status=SimulationRunStatus.COMPLETED,
                started_at=now,
                ended_at=now,
                kpis_json=step.kpis,
                result_json={
                    "kpis": step.kpis,
                    "optimization": {
                        "goal": goal.label,
                        "metric": goal.metric,
                        "metric_value": step.metric_value,
                        "satisfied": step.satisfied,
                    },
                },
            )
        )
        for event_type, payload in (
            (
                "simulation.created",
                {
                    "simulation_id": simulation.simulation_id,
                    "name": simulation.name,
                    "run_id": run.run_id,
                    "status": run.status,
                    "source": "optimizer",
                },
            ),
            (
                "simulation.run.updated",
                {
                    "simulation_id": simulation.simulation_id,
                    "run_id": run.run_id,
                    "status": run.status,
                    "speed_multiplier": run.speed_multiplier,
                    "source": "optimizer",
                },
            ),
        ):
            await self._events.publish(
                DomainEvent(
                    event_type=event_type,
                    correlation_id=correlation_id,
                    session_id=session_id,
                    payload=payload,
                )
            )
        return run

    def _optimization_report_message(self, outcome: OptimizationOutcome) -> str:
        goal = outcome.goal
        lines = [f"AGV 최적 대수 탐색 결과입니다. (목표: {goal.label})"]
        for step in outcome.steps:
            kpis = step.kpis
            verdict = "기준 충족 ✅" if step.satisfied else "기준 미달"
            lines.append(
                f"- AGV {step.agv_count}대 → 병목률 {step.metric_value:.1f}% · "
                f"처리량 {kpis.get('throughput', 0):.1f}/h · "
                f"평균대기 {kpis.get('avg_wait_time', 0):.1f}s · {verdict}"
            )
        if outcome.optimal_count is not None:
            tried_higher = [s for s in outcome.steps if s.agv_count > outcome.optimal_count]
            lines.append(
                f"최적 결과: AGV {outcome.optimal_count}대 — {goal.label}를 만족하는 최대 대수입니다."
            )
            if tried_higher:
                worst = tried_higher[0]
                lines.append(
                    f"(AGV {worst.agv_count}대는 병목률 {worst.metric_value:.1f}%로 기준을 초과해 "
                    f"{outcome.optimal_count}대로 줄였을 때 목표를 달성했습니다.)"
                )
        else:
            lines.append(
                f"탐색한 {goal.min_count}~{goal.max_count}대 범위에서는 {goal.label}를 만족하는 구성이 "
                "없었습니다. 목표 병목률을 완화하거나 경로/배치 정책을 조정해 다시 시도해 주세요."
            )
        return "\n".join(lines)

    async def _run_agv_optimization_live(
        self,
        session_id: str,
        correlation_id: str,
        goal: OptimizationGoal,
    ) -> None:
        """Live UE5 search loop (background): run each candidate for real, observe, decide.

        For each AGV count (max→min) it dispatches a real ``start_simulation`` to UE5, waits for
        that run's actual completion KPIs (the congestion heatmap → bottleneck rate), judges the
        goal, and stops at the first satisfying count. Progress streams as ``agent.optimize.*``
        events and the final report is delivered as a chat message.
        """
        await self._events.publish(
            DomainEvent(
                event_type="agent.optimize.started",
                correlation_id=correlation_id,
                session_id=session_id,
                payload={
                    "goal": goal.label,
                    "metric": goal.metric,
                    "comparator": goal.comparator,
                    "threshold": goal.threshold,
                    "max_count": goal.max_count,
                    "min_count": goal.min_count,
                    "mode": "live",
                },
            )
        )

        queue = await self._events.subscribe(session_id)
        steps: list[OptimizationStep] = []
        optimal: int | None = None
        try:
            counts = range(goal.max_count, goal.min_count - 1, -1)
            for index, count in enumerate(counts, start=1):
                command = await self._robot_commands.issue_robot_command(
                    session_id=session_id,
                    command_name=RobotCommandName.START_SIMULATION,
                    parameters={
                        "agv_count": count,
                        "speed_multiplier": 1.0,
                        "duration": _OPTIMIZE_RUN_DURATION_SEC,
                        "bottleneck_threshold_sec": 10.0,
                        "suppress_completion_report": True,
                    },
                    correlation_id=correlation_id,
                    idempotency_key=f"{correlation_id}:optimize:{count}",
                )
                if command.status == CommandStatus.FAILED:
                    await self._finish_optimization_failure(
                        session_id,
                        correlation_id,
                        f"AGV {count}대 시뮬레이션을 시뮬레이터에 전달하지 못해 탐색을 중단했습니다. "
                        "UE5 셀과 제어 서버(:7777)가 실행 중인지 확인해 주세요.",
                    )
                    return
                lifecycle_events = await self._sync_simulation_lifecycle(command)
                run_id = next(
                    (
                        ev.payload.get("run_id")
                        for ev in lifecycle_events
                        if ev.event_type == "simulation.created"
                    ),
                    command.command_id,
                )
                await self._events.publish(
                    DomainEvent(
                        event_type="agent.optimize.iteration",
                        correlation_id=correlation_id,
                        session_id=session_id,
                        command_id=command.command_id,
                        payload={
                            "phase": "running",
                            "index": index,
                            "agv_count": count,
                            "run_id": run_id,
                        },
                    )
                )

                try:
                    kpis = await asyncio.wait_for(
                        self._await_run_completion(queue, command.command_id),
                        timeout=_OPTIMIZE_RUN_TIMEOUT_SEC,
                    )
                except asyncio.TimeoutError:
                    await self._finish_optimization_failure(
                        session_id,
                        correlation_id,
                        f"AGV {count}대 시뮬레이션 결과를 {int(_OPTIMIZE_RUN_TIMEOUT_SEC)}초 내에 받지 "
                        "못해 탐색을 중단했습니다. UE5 실행 상태를 확인해 주세요.",
                    )
                    return
                except _RunFailedError as exc:
                    await self._finish_optimization_failure(
                        session_id,
                        correlation_id,
                        f"AGV {count}대 시뮬레이션이 실패해 탐색을 중단했습니다. (사유: {exc})",
                    )
                    return

                bottleneck = self._bottleneck_rate_from_kpis(kpis)
                kpis = {**kpis, "bottleneck_rate": bottleneck}
                satisfied = goal_satisfied(bottleneck, goal)
                step = OptimizationStep(
                    agv_count=count,
                    metric_value=bottleneck,
                    satisfied=satisfied,
                    kpis=kpis,
                )
                steps.append(step)
                await self._events.publish(
                    DomainEvent(
                        event_type="agent.optimize.iteration",
                        correlation_id=correlation_id,
                        session_id=session_id,
                        command_id=command.command_id,
                        payload={
                            "phase": "observed",
                            "index": index,
                            "agv_count": count,
                            "metric": goal.metric,
                            "metric_value": bottleneck,
                            "satisfied": satisfied,
                            "run_id": run_id,
                            "kpis": kpis,
                        },
                    )
                )
                # Surface this candidate's result and the next-step decision as a chat message
                # *before* the next run starts, so the operator sees why the search steps down.
                await self._publish_optimization_report(
                    session_id,
                    correlation_id,
                    self._optimization_step_message(
                        goal, step, self._next_search_count(goal, count, satisfied)
                    ),
                    kpis,
                )
                if satisfied:
                    optimal = count
                    break

            outcome = OptimizationOutcome(goal=goal, steps=steps, optimal_count=optimal)
            await self._events.publish(
                DomainEvent(
                    event_type="agent.optimize.completed",
                    correlation_id=correlation_id,
                    session_id=session_id,
                    payload={
                        "goal": goal.label,
                        "optimal_count": outcome.optimal_count,
                        "tried_counts": [step.agv_count for step in outcome.steps],
                        "mode": "live",
                    },
                )
            )
            optimal_kpis = next(
                (s.kpis for s in steps if s.agv_count == optimal), None
            )
            await self._publish_optimization_report(
                session_id,
                correlation_id,
                self._optimization_report_message(outcome),
                optimal_kpis,
            )
        finally:
            await self._events.unsubscribe(session_id, queue)

    async def _await_run_completion(self, queue, command_id: str) -> dict:
        """Block until the completion event for ``command_id`` arrives; return its KPIs.

        Other session events are drained and ignored. Raises ``_RunFailedError`` on a failure
        event. Wrap in ``asyncio.wait_for`` for a timeout.
        """
        while True:
            event = await queue.get()
            if event.command_id != command_id:
                continue
            if event.event_type == "robot.command.completed":
                kpis = event.payload.get("kpis")
                return kpis if isinstance(kpis, dict) else {}
            if event.event_type == "robot.command.failed":
                raise _RunFailedError(str(event.payload.get("reason") or "run failed"))

    def _bottleneck_rate_from_kpis(self, kpis: dict) -> float:
        """Read the bottleneck rate from completion KPIs, deriving it from the heatmap if absent."""
        value = kpis.get("bottleneck_rate")
        if isinstance(value, (int, float)):
            return float(value)
        return bottleneck_rate_from_heatmap(
            kpis.get("heatmap_grid") or [],
            int(kpis.get("heatmap_res_x") or 0),
            int(kpis.get("heatmap_res_y") or 0),
            kpis.get("heatmap_traversed_grid"),
        )

    async def _publish_optimization_report(
        self,
        session_id: str,
        correlation_id: str,
        content: str,
        kpis: dict | None = None,
    ) -> ChatMessage:
        """Deliver an optimization report as a chat message after the turn has already returned."""
        message = await self._add_assistant_message(session_id, content, correlation_id)
        payload: dict = {"message_id": message.message_id, "content": content}
        if isinstance(kpis, dict):
            payload["kpis"] = kpis
        await self._events.publish(
            DomainEvent(
                event_type="chat.report.generated",
                correlation_id=correlation_id,
                session_id=session_id,
                payload=payload,
            )
        )
        return message

    async def _finish_optimization_failure(
        self,
        session_id: str,
        correlation_id: str,
        reason: str,
    ) -> None:
        await self._events.publish(
            DomainEvent(
                event_type="agent.optimize.completed",
                correlation_id=correlation_id,
                session_id=session_id,
                payload={"error": reason, "mode": "live"},
            )
        )
        await self._publish_optimization_report(session_id, correlation_id, reason)

    def _simulation_lifecycle_event(
        self,
        event_type: str,
        command: RobotCommand,
        payload: dict,
    ) -> DomainEvent:
        return DomainEvent(
            event_type=event_type,
            correlation_id=command.correlation_id,
            session_id=command.session_id,
            command_id=command.command_id,
            payload=payload,
        )

    def _plan_for_request(self, user_text: str) -> tuple[list[str], str] | None:
        """Concise, deterministic plan for cheaply-detectable simple intents, else None.

        Returning None defers to the LLM planner, so only rote control commands are canned;
        variable requests still get a model-judged plan.
        """
        if self._is_optimize_request(user_text):
            return _optimize_plan_steps(user_text), "optimizer"
        if self._is_cancel_request(user_text):
            return _CANCEL_PLAN_STEPS, "deterministic"
        if self._is_explicit_sim_command(user_text):
            if self._is_simulation_start_request(user_text):
                return _SIM_START_PLAN_STEPS, "deterministic"
            return _SIM_CONTROL_PLAN_STEPS, "deterministic"
        return None

    def _is_simulation_start_request(self, user_text: str) -> bool:
        normalized = user_text.lower()
        if any(verb in normalized for verb in _SIM_STOP_VERBS):
            return False
        return any(verb in normalized for verb in _SIM_START_VERBS)

    async def _publish_agent_plan(
        self,
        session_id: str,
        user_text: str,
        correlation_id: str,
    ) -> list[DomainEvent]:
        deterministic = self._plan_for_request(user_text)
        if deterministic is not None:
            steps, source = deterministic
        else:
            # Genuinely variable requests (station task/move/inspect, free chat) keep an
            # LLM-judged plan so step count and content reflect the model's reading of the task.
            steps, source = await self._planning_agent.build_steps(
                user_message=user_text,
                correlation_id=correlation_id,
                llm=self._llm,
            )
        events = [
            DomainEvent(
                event_type="agent.plan.started",
                correlation_id=correlation_id,
                session_id=session_id,
                payload={"title": "에이전트 작업 플랜", "steps": steps},
            )
        ]
        # Label the plan honestly by its real origin: only an LLM-judged plan claims the model;
        # the optimizer/control plans are rule-based and must not be mislabeled as LLM output.
        plan_title = "LLM 실행 플랜 선택" if source == "llm" else "에이전트 작업 플랜 (규칙 기반)"
        events[0].payload.update({"title": plan_title, "source": source})
        events.extend(
            DomainEvent(
                event_type="agent.plan.step",
                correlation_id=correlation_id,
                session_id=session_id,
                payload={"index": index, "total": len(steps), "text": step},
            )
            for index, step in enumerate(steps, start=1)
        )
        events.append(
            DomainEvent(
                event_type="agent.plan.completed",
                correlation_id=correlation_id,
                session_id=session_id,
                payload={"step_count": len(steps), "source": source},
            )
        )
        for event in events:
            await self._events.publish(event)
        return events

    async def _classify_route(
        self,
        user_text: str,
        correlation_id: str,
    ) -> tuple[str, str]:
        """LLM-first intent routing with a deterministic keyword fallback.

        Returns ``(route, source)`` where ``source`` is ``"llm"`` or ``"keyword"``. The keyword
        path is the safety net when the LLM is unavailable or ambiguous, so a flaky Ollama
        degrades gracefully instead of freezing the turn.
        """
        # A goal-seeking "find the optimal AGV count" request is a deterministic intent the LLM
        # prompt doesn't model, so a direct check wins outright (and is checked before compare,
        # since "최적 ... 찾아" carries neither a compare nor a lifecycle verb).
        if self._is_optimize_request(user_text):
            return "optimize_agvs", "keyword"
        # "비교/compare" is an unambiguous read intent the LLM prompt doesn't know about, so a
        # deterministic check wins outright — but never over an explicit sim lifecycle command
        # (e.g. a stray "비교" inside "...비교하게 다시 돌려줘").
        if self._is_compare_request(user_text) and not self._is_explicit_sim_command(user_text):
            return "compare_runs", "keyword"
        # A mid-run "current status / AGV 상태" question is a live read the intent prompt doesn't
        # model. It wins over the LLM (which tends to collapse it into the KPI-only process_status)
        # but never over an explicit sim lifecycle command.
        if self._is_simulation_status_request(user_text) and not self._is_explicit_sim_command(user_text):
            return "simulation_status", "keyword"
        try:
            intent = await self._llm.classify_intent(user_text, correlation_id)
        except Exception:  # LLM boundary: never let routing fail the whole turn.
            intent = None
        if intent in _VALID_ROUTES:
            # Ollama sometimes misroutes an explicit "시뮬레이션 시작/정지" control phrase to a
            # read/query intent. An unambiguous sim lifecycle phrase always wins so chat-driven
            # start/stop actually runs (and registers in the simulation list).
            if intent != "robot_command" and self._is_explicit_sim_command(user_text):
                return "robot_command", "llm_guard"
            return intent, "llm"
        if self._is_process_status_request(user_text):
            return "process_status", "keyword"
        if self._is_station_action_query(user_text):
            return "station_action_query", "keyword"
        return "robot_command", "keyword"

    def _is_process_status_request(self, text: str) -> bool:
        normalized = text.lower()
        if (
            any(keyword in normalized for keyword in ("process status", "telemetry", "공정", "가동률", "처리량", "kpi"))
            and any(keyword in normalized for keyword in ("status", "상태", "확인", "조회", "알려"))
        ):
            return True
        return (
            ("공정" in text and ("상태" in text or "확인" in text or "조회" in text))
            or ("가상" in text and "상태" in text)
            or "process status" in normalized
        )

    def _is_station_action_query(self, text: str) -> bool:
        normalized = text.lower()
        action_query_keywords = (
            "가능한 행동",
            "할 수 있",
            "뭘 할",
            "무엇을 할",
            "가능한 작업",
            "작업 가능한",
            "작업 가능",
            "available action",
            "what can",
        )
        return any(keyword in normalized for keyword in action_query_keywords)

    def _available_actions_message(self, stations: list) -> str:
        ready_and_accessible = [
            station for station in stations if station.task_ready and station.accessible
        ]
        ready_blocked = [
            station for station in stations if station.task_ready and not station.accessible
        ]
        inspectable = sorted(stations, key=lambda station: station.station_id)

        lines = ["현재 가능한 작업은 다음과 같습니다."]
        if ready_and_accessible:
            targets = ", ".join(
                f"{station.station_id}번 스테이션({station.station_type})" for station in ready_and_accessible
            )
            lines.append(f"- 작업 가능: {targets}")
        else:
            lines.append("- 작업 가능: AGV가 즉시 접근해서 작업할 수 있는 스테이션이 없습니다.")

        if ready_blocked:
            targets = ", ".join(
                f"{station.station_id}번 스테이션({station.station_type}, AGV 접근 불가)" for station in ready_blocked
            )
            lines.append(f"- 작업 준비는 됐지만 경로 확인 필요: {targets}")

        lines.append(
            "- 점검 가능: "
            + ", ".join(f"{station.station_id}번 스테이션({station.state})" for station in inspectable)
        )
        movable = [station for station in inspectable if station.accessible]
        lines.append(
            "- 이동 가능: "
            + ", ".join(f"{station.station_id}번 스테이션" for station in movable)
        )
        lines.append(
            "원하시면 '2번 스테이션 작업해' 또는 '1번 스테이션 점검해'처럼 바로 실행할 수 있습니다. "
            "'시뮬레이션 시작/정지/일시정지', '속도 1.5배'처럼 공정 제어도 가능합니다."
        )
        return "\n".join(lines)

    def _station_task_blocked_message(self, station) -> str:
        reason = (
            f"공정 상태가 '{station.state}'이며 task_ready=false입니다."
            if station.state != "unknown"
            else "관제 서버의 task_ready 값이 false입니다."
        )
        alternatives = [
            f"{station.station_id}번 스테이션 점검",
        ]
        if station.accessible:
            alternatives.append(f"{station.station_id}번 스테이션으로 AGV 이동")
        return (
            f"{station.station_id}번 스테이션은 현재 작업 가능 상태가 아니어서 AGV 작업 명령을 발행하지 않았습니다. "
            f"이유: {reason} 현재 가능한 대안은 {', '.join(alternatives)}입니다. "
            "작업 가능한 스테이션 목록이 필요하면 '작업 가능한 스테이션이 있나?'라고 물어보세요."
        )

    def _is_cancel_request(self, text: str) -> bool:
        normalized = text.lower()
        if any(keyword in normalized for keyword in ("cancel", "취소")):
            return True
        return ("취소" in text and ("agv" in normalized or "작업" in text or "명령" in text)) or "cancel" in normalized

    def _is_confirmation_request(self, text: str) -> bool:
        normalized = text.lower().strip()
        return normalized in {
            "confirm",
            "yes",
            "y",
            "proceed",
            "approve",
            "ok",
            "execute",
            "확인",
            "승인",
            "진행",
            "실행",
        }

    def _is_abort_request(self, text: str) -> bool:
        normalized = text.lower()
        return any(keyword in normalized for keyword in ("abort", "emergency stop", "비상정지", "중단"))

    async def _safety_confirmation_required(
        self,
        session_id: str,
        user_text: str,
        tool_call: ValidatedToolCall,
        correlation_id: str,
    ) -> str | None:
        dangerous = {
            RobotCommandName.CANCEL_COMMAND,
        }
        if tool_call.name == RobotCommandName.STOP_SIMULATION and self._is_abort_request(user_text):
            dangerous.add(RobotCommandName.STOP_SIMULATION)
        if tool_call.name not in dangerous:
            return None
        if self._is_confirmation_request(user_text):
            return None
        self._pending_confirmations[session_id] = tool_call
        await self._events.publish(
            DomainEvent(
                event_type="agent.safety.confirmation_required",
                correlation_id=correlation_id,
                session_id=session_id,
                payload={
                    "tool_name": tool_call.name.value,
                    "arguments": tool_call.arguments,
                },
            )
        )
        return (
            "This command will stop or cancel active AGV/simulation work. "
            "Reply 'confirm' to execute it, or send another command to leave it pending."
        )

    def _consume_pending_confirmation(
        self,
        session_id: str,
        user_text: str,
    ) -> ValidatedToolCall | None:
        if not self._is_confirmation_request(user_text):
            return None
        return self._pending_confirmations.pop(session_id, None)

    async def _latest_cancelable_command(self, session_id: str):
        commands = await self._repository.list_commands(session_id)
        cancelable_statuses = {
            CommandStatus.PENDING,
            CommandStatus.ACCEPTED,
            CommandStatus.RUNNING,
        }
        for command in reversed(commands):
            if (
                command.command_name != RobotCommandName.CANCEL_COMMAND
                and command.status in cancelable_statuses
            ):
                return command
        return None

    def _process_status_message(self, telemetry: ProcessTelemetry) -> str:
        return (
            "가상 공정 상태입니다. "
            f"처리량 {telemetry.throughput:.1f} 작업/시간, "
            f"가동 AGV {telemetry.active_agvs}대, "
            f"평균 대기 {telemetry.avg_wait_time:.1f}s, "
            f"충돌 위험 {telemetry.collision_risk:.3f} 건/시간, "
            f"가동률 {telemetry.uptime:.0%}입니다."
        )

    def _accepted_message(
        self,
        command_name: RobotCommandName,
        arguments: dict,
        command_id: str,
        *,
        run_id: str | None = None,
    ) -> str:
        station_id = arguments.get("station_id")
        if command_name == RobotCommandName.RUN_STATION_TASK:
            return f"{station_id}번 스테이션 작업 명령을 접수했습니다. command_id={command_id}"
        if command_name == RobotCommandName.MOVE_TO_STATION:
            return f"AGV를 {station_id}번 스테이션으로 이동시키는 명령을 접수했습니다. command_id={command_id}"
        if command_name == RobotCommandName.INSPECT_STATION:
            return f"{station_id}번 스테이션 점검 명령을 접수했습니다. command_id={command_id}"
        if command_name == RobotCommandName.START_SIMULATION:
            return f"가상 공정 시뮬레이션 시작 명령을 접수했습니다. command_id={command_id}"
        if command_name == RobotCommandName.STOP_SIMULATION:
            return f"가상 공정 시뮬레이션 정지 명령을 접수했습니다. command_id={command_id}"
        if command_name == RobotCommandName.PAUSE_SIMULATION:
            return f"시뮬레이션 일시정지 명령을 접수했습니다. command_id={command_id}"
        if command_name == RobotCommandName.RESUME_SIMULATION:
            return f"시뮬레이션 재개 명령을 접수했습니다. command_id={command_id}"
        if command_name == RobotCommandName.SET_SIM_SPEED:
            speed = arguments.get("speed_multiplier")
            return f"시뮬레이션 속도를 {speed}배로 설정하는 명령을 접수했습니다. command_id={command_id}"
        return f"AGV 명령을 접수했습니다. command_id={command_id}"
_VALID_ROUTES = {
    "process_status",
    "simulation_status",
    "station_action_query",
    "robot_command",
    "compare_runs",
    "optimize_agvs",
    "general_chat",
}

# Verbs that express a simulation/command *action*. When present, the message is a
# control request — even if it also names KPI nouns as acceptance targets ("처리량 70 이상,
# 충돌 0건") — and must not be hijacked by the process-status read path.
_SIM_ACTION_KEYWORDS = (
    "돌려",
    "돌리",
    "돌린",
    "돌립",
    "실행",
    "시작",
    "배치",
    "투입",
    "정지",
    "중단",
    "멈춰",
    "일시정지",
    "재개",
    "배속",
    "속도",
    "start",
    "run",
    "launch",
    "deploy",
    "stop",
    "pause",
    "resume",
)
_STATUS_TOPIC_KEYWORDS = (
    "process status",
    "telemetry",
    "kpi",
    "공정",
    "현재 상태",
    "처리량",
    "충돌 위험",
    "병목",
    "가동률",
)
_STATUS_QUERY_KEYWORDS = (
    "status",
    "상태",
    "어때",
    "어떻",
    "알려",
    "확인",
    "조회",
    "보여",
    "?",
)


# Phrasings that ask for a live snapshot of the running cell (per-AGV state + collisions), as
# opposed to the KPI-only process_status read. Matched (minus any control verb) to route to the
# richer simulation_status report sourced from the live telemetry hub.
_SIM_STATUS_KEYWORDS = (
    "agv 상태",
    "agv상태",
    "에이전트 상태",
    "시뮬레이션 상태",
    "시뮬 상태",
    "현재 상태",
    "지금 상태",
    "지금 상황",
    "현재 상황",
    "진행 상황",
    "어떻게 돼가",
    "어떻게 되고",
    "어떻게 진행",
    "가동 중",
    "가동중",
    "몇 대",
    "simulation status",
    "sim status",
    "current status",
    "how is it going",
    "how's it going",
)


_SIM_TOPIC_KEYWORDS = ("시뮬레이션", "simulation", "sim", "공정 가동", "agv")
_SIM_LIFECYCLE_VERBS = (
    "시작",
    "정지",
    "중단",
    "멈춰",
    "일시정지",
    "재개",
    "돌려",
    "돌리",
    "돌린",
    "돌립",
    "배치",
    "투입",
    "start",
    "stop",
    "pause",
    "resume",
    "run",
    "launch",
    "deploy",
)


def _clean_is_explicit_sim_command(self: ChatOrchestrator, text: str) -> bool:
    """True only for an unambiguous simulation lifecycle phrase (sim topic + control verb).

    Deliberately narrow: a bare KPI/status question ('현재 속도 어때?', 'AGV 상태 알려줘') has no
    lifecycle verb, so it is never pulled into the command path by this guard.
    """
    normalized = text.lower()
    return any(topic in normalized for topic in _SIM_TOPIC_KEYWORDS) and any(
        verb in normalized for verb in _SIM_LIFECYCLE_VERBS
    )


def _clean_is_process_status_request(self: ChatOrchestrator, text: str) -> bool:
    normalized = text.lower()
    if any(keyword in normalized for keyword in _SIM_ACTION_KEYWORDS):
        return False
    return any(topic in normalized for topic in _STATUS_TOPIC_KEYWORDS) and any(
        query in normalized for query in _STATUS_QUERY_KEYWORDS
    )


def _clean_is_simulation_status_request(self: ChatOrchestrator, text: str) -> bool:
    """True for a live "how is the run doing / AGV 상태" question (not a control command).

    Excludes any control verb so "시뮬레이션 시작/정지" still routes to the command path.
    """
    normalized = text.lower()
    if any(keyword in normalized for keyword in _SIM_ACTION_KEYWORDS):
        return False
    return any(keyword in normalized for keyword in _SIM_STATUS_KEYWORDS)


# Live AGV state strings (UE5 AGVStateHelpers) that count as actively operating; STOPPED_COLLISION
# is reported separately and IDLE / STOPPED_OPERATION are treated as not operating.
_OPERATING_AGV_STATES = {"LOADING", "UNLOADING", "WAITING_AT_SECTION"}
_AGV_STATE_LABELS = {
    "IDLE": "대기",
    "MOVING_TO_PICKUP": "픽업 이동 중",
    "MOVING_TO_DROPOFF": "드롭오프 이동 중",
    "MOVING_TO_STATION": "스테이션 이동 중",
    "LOADING": "적재 중",
    "UNLOADING": "하역 중",
    "WAITING_AT_SECTION": "교차로 대기",
    "STOPPED_COLLISION": "충돌 정지",
    "STOPPED_OPERATION": "운행 정지",
}


def _is_operating_state(state: str) -> bool:
    return state.startswith("MOVING") or state in _OPERATING_AGV_STATES


def _clean_simulation_status_message(
    self: ChatOrchestrator,
    agvs: list[dict],
    process: dict | None,
) -> str:
    if not agvs:
        return (
            "현재 실행 중인 시뮬레이션이 없습니다. "
            "'시뮬레이션 시작해줘'로 시작한 뒤 다시 상태를 물어봐 주세요."
        )
    operating: list[str] = []
    collided: list[str] = []
    other: list[str] = []
    for agv in agvs:
        agv_id = str(agv.get("agv_id", "?"))
        state = str(agv.get("state", "")).upper()
        label = _AGV_STATE_LABELS.get(state, state or "알 수 없음")
        entry = f"{agv_id}({label})"
        if state == "STOPPED_COLLISION":
            collided.append(entry)
        elif _is_operating_state(state):
            operating.append(entry)
        else:
            other.append(entry)

    lines = [f"현재 시뮬레이션 상태입니다. (가동 AGV {len(operating)}/{len(agvs)}대)"]
    if isinstance(process, dict) and isinstance(process.get("uptime"), (int, float)):
        lines.append(f"- 가동률(작업률): {float(process['uptime']):.0%}")
    if operating:
        lines.append(f"- 가동 중: {', '.join(operating)}")
    if other:
        lines.append(f"- 대기/정지: {', '.join(other)}")
    if collided:
        lines.append(f"- ⚠️ 충돌 정지: {', '.join(collided)}")
    else:
        lines.append("- 충돌: 없음")
    return "\n".join(lines)


def _clean_is_station_action_query(self: ChatOrchestrator, text: str) -> bool:
    normalized = text.lower()
    return any(
        keyword in normalized
        for keyword in (
            "available action",
            "what can",
            "가능한 작업",
            "어떤 작업",
            "뭘 할 수",
        )
    )


def _clean_is_cancel_request(self: ChatOrchestrator, text: str) -> bool:
    normalized = text.lower()
    return "cancel" in normalized or "취소" in normalized


def _clean_is_compare_request(self: ChatOrchestrator, text: str) -> bool:
    normalized = text.lower()
    return any(
        keyword in normalized
        for keyword in (
            "비교",
            "compare",
            "대비",
            " vs ",
            "어느 게 더",
            "어느게 더",
            "어느 쪽이",
            "뭐가 더",
            "더 나아",
            "더 나은",
        )
    )


def _clean_is_optimize_request(self: ChatOrchestrator, text: str) -> bool:
    return is_optimize_request(text)


def _clean_process_status_message(self: ChatOrchestrator, telemetry: ProcessTelemetry) -> str:
    return (
        "현재 공정 상태입니다. "
        f"처리량 {telemetry.throughput:.1f} tasks/h, "
        f"가동 AGV {telemetry.active_agvs}대, "
        f"평균 대기 {telemetry.avg_wait_time:.1f}s, "
        f"충돌 위험 {telemetry.collision_risk:.3f}/h, "
        f"가동률 {telemetry.uptime:.0%}."
    )


def _clean_available_actions_message(self: ChatOrchestrator, stations: list) -> str:
    ready = [station for station in stations if station.task_ready and station.accessible]
    lines = ["현재 가능한 작업입니다."]
    if ready:
        lines.append(
            "- 작업 가능: "
            + ", ".join(f"{station.station_id}번 스테이션({station.station_type})" for station in ready)
        )
    else:
        lines.append("- 즉시 작업 가능한 스테이션이 없습니다.")
    lines.append(
        "- 예시: '2번 스테이션 작업해줘', '1번 스테이션 점검해', '시뮬레이션 시작해줘', '속도 4배로 바꿔'."
    )
    return "\n".join(lines)


def _clean_station_task_blocked_message(self: ChatOrchestrator, station) -> str:
    return (
        f"{station.station_id}번 스테이션은 현재 작업 가능한 상태가 아닙니다. "
        f"현재 상태: {station.state}, 접근 가능: {station.accessible}."
    )


def _clean_accepted_message(
    self: ChatOrchestrator,
    command_name: RobotCommandName,
    arguments: dict,
    command_id: str,
    *,
    run_id: str | None = None,
) -> str:
    station_id = arguments.get("station_id")
    if command_name == RobotCommandName.RUN_STATION_TASK:
        return f"{station_id}번 스테이션 작업을 시작합니다."
    if command_name == RobotCommandName.MOVE_TO_STATION:
        return f"AGV를 {station_id}번 스테이션으로 이동시킵니다."
    if command_name == RobotCommandName.INSPECT_STATION:
        return f"{station_id}번 스테이션 점검을 시작합니다."
    if command_name == RobotCommandName.START_SIMULATION:
        count = int(arguments.get("agv_count") or 3)
        speed = float(arguments.get("speed_multiplier") or 1.0)
        duration = int(arguments.get("duration_seconds") or arguments.get("duration") or 600)
        acceptance = arguments.get("acceptance")
        lines = ["시뮬레이션을 시작합니다."]
        lines.append(f"- AGV {count}대 · 속도 {speed:g}배속 · 실행 {duration}초")
        if isinstance(acceptance, list) and acceptance:
            labels = [a.get("label") or a.get("metric", "") for a in acceptance if isinstance(a, dict)]
            labels = [lbl for lbl in labels if lbl]
            if labels:
                lines.append(f"- 수용 기준: {', '.join(labels)}")
        if run_id:
            lines.append(f"- 실행 ID: {run_id[-8:]}")
        return "\n".join(lines)
    if command_name == RobotCommandName.STOP_SIMULATION:
        return "시뮬레이션을 정지합니다."
    if command_name == RobotCommandName.PAUSE_SIMULATION:
        return "시뮬레이션을 일시정지합니다."
    if command_name == RobotCommandName.RESUME_SIMULATION:
        return "시뮬레이션을 재개합니다."
    if command_name == RobotCommandName.SET_SIM_SPEED:
        speed = arguments.get("speed_multiplier")
        return f"시뮬레이션 속도를 {speed}배로 변경합니다."
    return "AGV 명령을 접수했습니다."


def _clean_command_dispatch_failed_message(
    self: ChatOrchestrator,
    command_name: RobotCommandName,
) -> str:
    """Operator-facing message when UE5 rejected/never received the command."""
    if command_name == RobotCommandName.START_SIMULATION:
        return (
            "시뮬레이터에 연결하지 못해 시뮬레이션을 시작하지 못했습니다. "
            "UE5 AGV 셀이 실행 중이고 제어 서버(:7777)가 떠 있는지 확인한 뒤 다시 시도해 주세요."
        )
    return (
        "시뮬레이터에 연결하지 못해 명령을 전달하지 못했습니다. "
        "UE5 AGV 셀이 실행 중인지 확인한 뒤 다시 시도해 주세요."
    )


async def _clean_general_chat_message(
    self: ChatOrchestrator,
    user_text: str,
    session_id: str,
    correlation_id: str,
    knowledge: list[RetrievedChunk] | None = None,
) -> str:
    """Free-form conversational response using recent session history as context."""
    recent = await self._repository.list_messages(session_id, limit=10)
    history = [
        {"role": msg.role.value, "content": msg.content}
        for msg in recent
        if msg.content and msg.role.value in ("user", "assistant")
    ]
    try:
        return await self._llm.generate_chat_response(
            user_text, history, correlation_id, knowledge=knowledge
        )
    except Exception:
        return (
            "저는 AGV 공정 제어 어시스턴트입니다. "
            "시뮬레이션 시작/정지, 공정 상태 조회, 스테이션 작업 지시 등을 도와드릴 수 있습니다.\n"
            "무엇을 도와드릴까요?"
        )


ChatOrchestrator._is_explicit_sim_command = _clean_is_explicit_sim_command
ChatOrchestrator._is_process_status_request = _clean_is_process_status_request
ChatOrchestrator._is_simulation_status_request = _clean_is_simulation_status_request
ChatOrchestrator._simulation_status_message = _clean_simulation_status_message
ChatOrchestrator._is_station_action_query = _clean_is_station_action_query
ChatOrchestrator._is_cancel_request = _clean_is_cancel_request
ChatOrchestrator._is_compare_request = _clean_is_compare_request
ChatOrchestrator._is_optimize_request = _clean_is_optimize_request
ChatOrchestrator._process_status_message = _clean_process_status_message
ChatOrchestrator._available_actions_message = _clean_available_actions_message
ChatOrchestrator._station_task_blocked_message = _clean_station_task_blocked_message
ChatOrchestrator._command_dispatch_failed_message = _clean_command_dispatch_failed_message
ChatOrchestrator._accepted_message = _clean_accepted_message
ChatOrchestrator._general_chat_message = _clean_general_chat_message
