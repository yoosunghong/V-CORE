from __future__ import annotations

from app.domain.models import CommandStatus, ProcessTelemetry, RobotCommand


class DemoIotCommandClient:
    """In-memory mock that keeps the AGV command boundary testable."""

    async def send_robot_command(self, command: RobotCommand) -> RobotCommand:
        command.status = CommandStatus.ACCEPTED
        return command

    async def get_process_telemetry(self, correlation_id: str) -> ProcessTelemetry:
        return ProcessTelemetry(
            throughput=68.2,
            active_agvs=3,
            avg_wait_time=12.0,
            collision_risk=0.0,
            uptime=0.97,
        )
