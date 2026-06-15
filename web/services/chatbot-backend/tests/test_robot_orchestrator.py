from __future__ import annotations

import asyncio

from app.application.robot_orchestrator import RobotCommandOrchestrator
from app.domain.models import CommandStatus, RobotCommandName
from app.infrastructure.event_bus import InMemoryEventBus
from app.infrastructure.iot_client import DemoIotCommandClient
from app.infrastructure.repositories import InMemorySessionRepository


def test_robot_command_idempotency_reuses_existing_command_without_resending() -> None:
    async def run() -> tuple[str, str, list[str], int]:
        repository = InMemorySessionRepository()
        events = InMemoryEventBus()
        iot_client = CountingIotClient()
        orchestrator = RobotCommandOrchestrator(
            repository=repository,
            iot_client=iot_client,
            events=events,
        )

        first = await orchestrator.issue_robot_command(
            session_id="session_idem",
            command_name=RobotCommandName.RUN_STATION_TASK,
            parameters={"station_id": 2},
            correlation_id="corr_first",
            idempotency_key="idem-001",
        )
        second = await orchestrator.issue_robot_command(
            session_id="session_idem",
            command_name=RobotCommandName.RUN_STATION_TASK,
            parameters={"station_id": 2},
            correlation_id="corr_retry",
            idempotency_key="idem-001",
        )
        history = await events.history("session_idem")
        return (
            first.command_id,
            second.command_id,
            [event.event_type for event in history],
            iot_client.send_count,
        )

    first_id, second_id, event_types, send_count = asyncio.run(run())

    assert first_id == second_id
    assert send_count == 1
    assert event_types == [
        "robot.command.requested",
        "robot.command.accepted",
        "robot.command.reused",
    ]


def test_failed_dispatch_is_not_reported_as_accepted() -> None:
    async def run() -> tuple[CommandStatus, list[str]]:
        repository = InMemorySessionRepository()
        events = InMemoryEventBus()
        orchestrator = RobotCommandOrchestrator(
            repository=repository,
            iot_client=FailingIotClient(),
            events=events,
        )

        command = await orchestrator.issue_robot_command(
            session_id="session_fail",
            command_name=RobotCommandName.START_SIMULATION,
            parameters={"agv_count": 2},
            correlation_id="corr_fail",
            idempotency_key="idem-fail",
        )
        history = await events.history("session_fail")
        return command.status, [event.event_type for event in history]

    status, event_types = asyncio.run(run())

    assert status == CommandStatus.FAILED
    assert event_types == [
        "robot.command.requested",
        "robot.command.failed",
    ]


class CountingIotClient(DemoIotCommandClient):
    def __init__(self) -> None:
        self.send_count = 0

    async def send_robot_command(self, command):
        self.send_count += 1
        command.status = CommandStatus.ACCEPTED
        return command


class FailingIotClient(DemoIotCommandClient):
    """Mimics Ue5CommandClient when UE5 is unreachable."""

    async def send_robot_command(self, command):
        command.status = CommandStatus.FAILED
        return command
