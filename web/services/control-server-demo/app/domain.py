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


class TaskStatus(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Station(BaseModel):
    station_id: int
    station_type: str
    task_ready: bool
    cell_id: str = "cell_demo"
    zone: str = "A"
    state: str
    accessible: bool = True
    last_inspected_at: datetime = Field(default_factory=utc_now)


class ProcessTelemetry(BaseModel):
    throughput: float
    active_agvs: int
    avg_wait_time: float
    collision_risk: float
    uptime: float
    measured_at: datetime = Field(default_factory=utc_now)


class CellStatus(BaseModel):
    cell_id: str
    stations: list[Station]
    telemetry: ProcessTelemetry


class ControlTask(BaseModel):
    task_id: str = Field(default_factory=lambda: new_id("task"))
    command_name: str
    target_type: str
    target_id: str
    correlation_id: str
    idempotency_key: str
    status: TaskStatus = TaskStatus.ACCEPTED
    parameters: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ControlEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    event_type: str
    correlation_id: str
    task_id: str | None = None
    occurred_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
