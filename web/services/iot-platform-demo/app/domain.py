from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class StrEnum(str, Enum):
    pass


class RobotStatus(StrEnum):
    IDLE = "idle"
    MOVING = "moving"
    HARVESTING = "harvesting"
    INSPECTING = "inspecting"
    COMPLETED = "completed"
    FAILED = "failed"


class CommandStatus(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RobotCommandName(StrEnum):
    HARVEST_BED = "harvest_bed"
    MOVE_TO_BED = "move_to_bed"
    INSPECT_BED = "inspect_bed"
    CANCEL_ROBOT_COMMAND = "cancel_robot_command"


class Robot(BaseModel):
    robot_id: str
    display_name: str
    status: RobotStatus
    current_bed_id: int | None = None
    battery_percent: int = Field(ge=0, le=100)
    updated_at: datetime = Field(default_factory=utc_now)


class SensorSnapshot(BaseModel):
    greenhouse_id: str = "greenhouse_demo"
    temperature_celsius: float
    humidity_percent: float
    co2_ppm: int
    illuminance_lux: int
    measured_at: datetime = Field(default_factory=utc_now)


class Actuator(BaseModel):
    actuator_id: str
    actuator_type: str
    status: str
    updated_at: datetime = Field(default_factory=utc_now)


class RobotCommand(BaseModel):
    command_id: str
    session_id: str
    command_name: RobotCommandName
    correlation_id: str
    idempotency_key: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    status: CommandStatus = CommandStatus.ACCEPTED
    robot_id: str = "robot_demo_1"
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class IotEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    event_type: str
    correlation_id: str
    session_id: str | None = None
    command_id: str | None = None
    occurred_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
