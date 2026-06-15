from __future__ import annotations

import asyncio

from app.domain.models import DomainEvent, RobotCommand, RobotCommandName
from app.infrastructure.container import AppContainer


def test_suppressed_optimizer_completion_does_not_persist_generic_report() -> None:
    orch = AppContainer().chat

    async def main() -> tuple[str, int]:
        command = await orch._repository.save_command(
            RobotCommand(
                session_id="session_suppress",
                command_name=RobotCommandName.START_SIMULATION,
                correlation_id="corr",
                idempotency_key="suppress",
                parameters={"suppress_completion_report": True},
            )
        )
        message = await orch.handle_completion_event(
            DomainEvent(
                event_type="robot.command.completed",
                correlation_id="corr",
                session_id="session_suppress",
                command_id=command.command_id,
                payload={"kpis": {"throughput": 1.0}},
            )
        )
        messages = await orch._repository.list_messages("session_suppress")
        return message.content, len(messages)

    content, message_count = asyncio.run(main())
    assert content == ""
    assert message_count == 0
