from __future__ import annotations

from app.domain import (
    Actuator,
    CommandStatus,
    IotEvent,
    Robot,
    RobotCommand,
    RobotCommandName,
    RobotStatus,
    SensorSnapshot,
    utc_now,
)


class InMemoryIotRepository:
    def __init__(self) -> None:
        self._robots: dict[str, Robot] = {
            "robot_demo_1": Robot(
                robot_id="robot_demo_1",
                display_name="Demo Harvest Robot 1",
                status=RobotStatus.IDLE,
                current_bed_id=1,
                battery_percent=87,
            )
        }
        self._actuators: dict[str, Actuator] = {
            "fan_zone_a": Actuator(actuator_id="fan_zone_a", actuator_type="fan", status="auto"),
            "light_zone_b": Actuator(
                actuator_id="light_zone_b",
                actuator_type="light",
                status="on",
            ),
        }
        self._commands: dict[str, RobotCommand] = {}
        self._idempotency_index: dict[str, str] = {}
        self._events: list[IotEvent] = []

    async def list_robots(self) -> list[Robot]:
        return list(self._robots.values())

    async def get_robot(self, robot_id: str) -> Robot | None:
        return self._robots.get(robot_id)

    async def sensor_snapshot(self) -> SensorSnapshot:
        return SensorSnapshot(
            temperature_celsius=23.4,
            humidity_percent=62.5,
            co2_ppm=810,
            illuminance_lux=18400,
        )

    async def list_actuators(self) -> list[Actuator]:
        return list(self._actuators.values())

    async def set_actuator_status(self, actuator_id: str, status: str) -> Actuator | None:
        actuator = self._actuators.get(actuator_id)
        if actuator is None:
            return None
        actuator.status = status
        actuator.updated_at = utc_now()
        await self.publish_event(
            IotEvent(
                event_type="actuator.state.changed",
                correlation_id=f"corr_{actuator_id}",
                payload={"actuator_id": actuator_id, "status": status},
            )
        )
        return actuator

    async def accept_command(self, command: RobotCommand) -> RobotCommand:
        existing_command_id = self._idempotency_index.get(command.idempotency_key)
        if existing_command_id:
            return self._commands[existing_command_id]
        self._commands[command.command_id] = command
        self._idempotency_index[command.idempotency_key] = command.command_id
        await self.publish_event(
            IotEvent(
                event_type="robot.command.accepted",
                correlation_id=command.correlation_id,
                session_id=command.session_id,
                command_id=command.command_id,
                payload={
                    "robot_id": command.robot_id,
                    "command_name": command.command_name,
                    "parameters": command.parameters,
                },
            )
        )
        await self.simulate_command_progress(command.command_id)
        return command

    async def get_command(self, command_id: str) -> RobotCommand | None:
        return self._commands.get(command_id)

    async def simulate_command_progress(self, command_id: str) -> RobotCommand | None:
        command = self._commands.get(command_id)
        if command is None:
            return None
        robot = self._robots[command.robot_id]
        bed_id = command.parameters.get("bed_id")
        command.status = CommandStatus.RUNNING
        command.updated_at = utc_now()
        robot.status = RobotStatus.MOVING
        robot.current_bed_id = bed_id or robot.current_bed_id
        robot.updated_at = utc_now()
        await self.publish_event(
            IotEvent(
                event_type="robot.moving",
                correlation_id=command.correlation_id,
                session_id=command.session_id,
                command_id=command.command_id,
                payload={"robot_id": robot.robot_id, "target_bed_id": bed_id},
            )
        )

        work_status = self._work_status(command.command_name)
        robot.status = work_status
        robot.updated_at = utc_now()
        await self.publish_event(
            IotEvent(
                event_type=f"robot.{work_status.value}",
                correlation_id=command.correlation_id,
                session_id=command.session_id,
                command_id=command.command_id,
                payload={"robot_id": robot.robot_id, "bed_id": bed_id},
            )
        )

        command.status = CommandStatus.COMPLETED
        robot.status = RobotStatus.IDLE
        robot.updated_at = utc_now()
        command.updated_at = utc_now()
        await self.publish_event(
            IotEvent(
                event_type="robot.command.completed",
                correlation_id=command.correlation_id,
                session_id=command.session_id,
                command_id=command.command_id,
                payload={"robot_id": robot.robot_id, "bed_id": bed_id},
            )
        )
        return command

    async def fail_command(self, command_id: str, reason: str) -> RobotCommand | None:
        command = self._commands.get(command_id)
        if command is None:
            return None
        robot = self._robots[command.robot_id]
        command.status = CommandStatus.FAILED
        command.updated_at = utc_now()
        robot.status = RobotStatus.FAILED
        robot.updated_at = utc_now()
        await self.publish_event(
            IotEvent(
                event_type="robot.command.failed",
                correlation_id=command.correlation_id,
                session_id=command.session_id,
                command_id=command.command_id,
                payload={"robot_id": robot.robot_id, "reason": reason},
            )
        )
        return command

    async def publish_event(self, event: IotEvent) -> IotEvent:
        self._events.append(event)
        return event

    async def list_events(self) -> list[IotEvent]:
        return list(self._events)

    def _work_status(self, command_name: RobotCommandName) -> RobotStatus:
        if command_name == RobotCommandName.HARVEST_BED:
            return RobotStatus.HARVESTING
        if command_name == RobotCommandName.INSPECT_BED:
            return RobotStatus.INSPECTING
        return RobotStatus.COMPLETED
