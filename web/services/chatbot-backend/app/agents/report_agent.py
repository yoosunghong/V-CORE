from __future__ import annotations

from app.agents.failure_policy import LlmGatewayError
from app.application.ports import LlmGateway
from app.domain.evaluation import SimulationEvaluation, build_simulation_evaluation
from app.domain.models import (
    DomainEvent,
    RetrievedChunk,
    RobotCommand,
    RobotCommandName,
    format_verdict_summary,
)


def _collision_halt_notice(event: DomainEvent) -> str | None:
    """One-line notice when a run terminated because all AGVs were stopped by collisions.

    Returns None unless the completion event carries ``stop_reason == "collision_halt"``.
    """
    if event.payload.get("stop_reason") != "collision_halt":
        return None
    kpis = event.payload.get("kpis")
    collisions = kpis.get("collisions") if isinstance(kpis, dict) else None
    if isinstance(collisions, (int, float)) and not isinstance(collisions, bool):
        return f"⚠️ 시뮬레이션이 AGV 충돌로 전체 정지되어 종료되었습니다 (충돌 {int(collisions)}건). 아래는 종료 시점 결과입니다."
    return "⚠️ 시뮬레이션이 AGV 충돌로 전체 정지되어 종료되었습니다. 아래는 종료 시점 결과입니다."


class ReportAgent:
    def __init__(self, llm: LlmGateway) -> None:
        self._llm = llm

    async def generate_report(
        self,
        event: DomainEvent,
        command: RobotCommand,
        correlation_id: str,
        knowledge: list[RetrievedChunk] | None = None,
    ) -> str:
        # Qualitative evaluation of the heatmap + KPIs, woven into the LLM narrative so the
        # report reads as an assessment rather than a number dump. None for non-run commands.
        evaluation = build_simulation_evaluation(event.payload.get("kpis"), event.payload.get("verdict"))
        evaluation_block = evaluation.to_prompt_block() if evaluation else None
        try:
            report = await self._llm.generate_report(
                event, command, correlation_id, evaluation=evaluation_block, knowledge=knowledge
            )
        except LlmGatewayError:
            report = self._fallback_report(event, command, evaluation)
        # A collision halt is the simulation terminating because every AGV stopped on a
        # collision. Lead with a deterministic notice so the collision is always reported
        # regardless of what the LLM narrative produced.
        notice = _collision_halt_notice(event)
        return f"{notice}\n\n{report}" if notice else report

    def _fallback_report(
        self,
        event: DomainEvent,
        command: RobotCommand,
        evaluation: SimulationEvaluation | None = None,
    ) -> str:
        station_id = command.parameters.get("station_id")
        if event.event_type == "robot.command.completed":
            verdict_line = format_verdict_summary(event.payload.get("verdict"))
            if command.command_name == RobotCommandName.RUN_STATION_TASK:
                base = f"Station {station_id} task is complete."
            elif command.command_name == RobotCommandName.MOVE_TO_STATION:
                base = f"AGV move to station {station_id} is complete."
            elif command.command_name == RobotCommandName.INSPECT_STATION:
                base = f"Station {station_id} inspection is complete."
            elif command.command_name == RobotCommandName.START_SIMULATION:
                base = "Virtual Process simulation has started."
            elif command.command_name == RobotCommandName.STOP_SIMULATION:
                base = "Virtual Process simulation has stopped."
            else:
                base = f"AGV command {command.command_id} is complete."
            report = f"{base} {verdict_line}" if verdict_line else base
            if evaluation is not None:
                # Append the deterministic narrative so the qualitative assessment still
                # appears when the LLM is unavailable.
                report = f"{report}\n\n{evaluation.to_narrative()}"
            return report
        reason = event.payload.get("reason", "unknown")
        return f"AGV command {command.command_id} failed. Reason: {reason}"
