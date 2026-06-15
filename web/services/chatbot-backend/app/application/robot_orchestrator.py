from __future__ import annotations

from app.application.ports import EventPublisher, IotCommandClient, SessionRepository
from app.domain.models import (
    CommandStatus,
    DomainEvent,
    RobotCommand,
    RobotCommandName,
)


class RobotCommandOrchestrator:
    def __init__(
        self,
        repository: SessionRepository,
        iot_client: IotCommandClient,
        events: EventPublisher,
    ) -> None:
        self._repository = repository
        self._iot_client = iot_client
        self._events = events

    async def issue_robot_command(
        self,
        session_id: str,
        command_name: RobotCommandName,
        parameters: dict,
        correlation_id: str,
        idempotency_key: str,
    ) -> RobotCommand:
        existing = await self._repository.get_command_by_idempotency_key(idempotency_key)
        if existing is not None:
            await self._events.publish(
                DomainEvent(
                    event_type="robot.command.reused",
                    correlation_id=correlation_id,
                    session_id=session_id,
                    command_id=existing.command_id,
                    payload={
                        "idempotency_key": idempotency_key,
                        "status": existing.status,
                    },
                )
            )
            return existing

        command = RobotCommand(
            session_id=session_id,
            command_name=command_name,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            parameters=parameters,
        )
        new_command_id = command.command_id
        command = await self._repository.save_command(command)
        if command.command_id != new_command_id:
            await self._events.publish(
                DomainEvent(
                    event_type="robot.command.reused",
                    correlation_id=correlation_id,
                    session_id=session_id,
                    command_id=command.command_id,
                    payload={
                        "idempotency_key": idempotency_key,
                        "status": command.status,
                    },
                )
            )
            return command
        await self._events.publish(
            DomainEvent(
                event_type="robot.command.requested",
                correlation_id=correlation_id,
                session_id=session_id,
                command_id=command.command_id,
                payload={"command_name": command_name, "parameters": parameters},
            )
        )

        result = await self._iot_client.send_robot_command(command)
        await self._repository.update_command(result)
        await self._events.publish(
            DomainEvent(
                event_type=(
                    "robot.command.failed"
                    if result.status == CommandStatus.FAILED
                    else "robot.command.accepted"
                ),
                correlation_id=correlation_id,
                session_id=session_id,
                command_id=result.command_id,
                payload={"status": result.status},
            )
        )
        return result
