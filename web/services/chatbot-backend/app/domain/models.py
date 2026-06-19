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


def format_verdict_summary(verdict: Any) -> str | None:
    """Render a one-line PASS/FAIL summary from an F4 simulation verdict payload.

    Returns None when the payload is not a usable verdict, so callers can skip it.
    """
    if not isinstance(verdict, dict):
        return None
    passed_labels = verdict.get("passed_labels") or []
    failed_labels = verdict.get("failed_labels") or []
    if not passed_labels and not failed_labels:
        return None
    overall = "PASS" if verdict.get("passed") else "FAIL"
    parts = [f"Acceptance: {overall}"]
    if passed_labels:
        parts.append("passed [" + ", ".join(str(label) for label in passed_labels) + "]")
    if failed_labels:
        parts.append("failed [" + ", ".join(str(label) for label in failed_labels) + "]")
    return " — ".join(parts)


class StrEnum(str, Enum):
    pass


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class CommandStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING_CONFIRMATION = "pending_confirmation"


class SimulationRunStatus(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


class RobotCommandName(StrEnum):
    # Station-targeted AGV commands
    RUN_STATION_TASK = "run_station_task"
    MOVE_TO_STATION = "move_to_station"
    INSPECT_STATION = "inspect_station"
    CANCEL_COMMAND = "cancel_command"
    # Simulation lifecycle commands (Virtual Process control)
    START_SIMULATION = "start_simulation"
    STOP_SIMULATION = "stop_simulation"
    PAUSE_SIMULATION = "pause_simulation"
    RESUME_SIMULATION = "resume_simulation"
    SET_SIM_SPEED = "set_sim_speed"


SIM_LIFECYCLE_COMMANDS = frozenset(
    {
        RobotCommandName.START_SIMULATION,
        RobotCommandName.STOP_SIMULATION,
        RobotCommandName.PAUSE_SIMULATION,
        RobotCommandName.RESUME_SIMULATION,
        RobotCommandName.SET_SIM_SPEED,
    }
)


class Station(BaseModel):
    """A target station in the Virtual Process AGV cell."""

    station_id: int
    station_type: str
    task_ready: bool
    cell_id: str = "cell_demo"
    zone: str = "A"
    state: str = "unknown"
    accessible: bool = True


class ProcessTelemetry(BaseModel):
    """Live Virtual Process KPIs sourced from the UE5 simulation."""

    cell_id: str = "cell_demo"
    throughput: float
    active_agvs: int
    avg_wait_time: float
    collision_risk: float
    uptime: float
    # Level-authored fleet size (the cell's maximum AGV count). None when UE5 didn't report it,
    # so callers fall back to a configured default instead of assuming a fixed number.
    max_agvs: int | None = None
    measured_at: datetime = Field(default_factory=utc_now)


class RetrievedChunk(BaseModel):
    """A knowledge-base chunk returned by the KnowledgeGateway for RAG grounding."""

    document_id: str
    title: str
    text: str
    score: float
    source: str = "unknown"
    category: str = "unknown"


class Simulation(BaseModel):
    """Operator-authored runtime parameters for one UE5 AGV simulation."""

    simulation_id: str = Field(default_factory=lambda: new_id("simulation"))
    name: str
    agv_count: int = 3
    speed_multiplier: float = 1.0
    workload_percent: float = 100.0
    policy_id: str = "POLICY_FIFO"
    duration_seconds: int = 600
    bottleneck_threshold_sec: float = 10.0
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SimulationRun(BaseModel):
    """Saved execution record for a simulation run."""

    run_id: str = Field(default_factory=lambda: new_id("run"))
    simulation_id: str
    status: SimulationRunStatus = SimulationRunStatus.CREATED
    ue_run_id: str | None = None
    speed_multiplier: float = 1.0
    started_at: datetime | None = None
    ended_at: datetime | None = None
    result_json: dict[str, Any] | None = None
    kpis_json: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ChatSession(BaseModel):
    session_id: str = Field(default_factory=lambda: new_id("session"))
    user_id: str | None = None
    unreal_client_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ChatSessionSummary(ChatSession):
    message_count: int = 0
    last_message_at: datetime | None = None
    last_message_preview: str | None = None
    first_user_message_preview: str | None = None


class ChatMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: new_id("msg"))
    session_id: str
    role: MessageRole
    content: str
    correlation_id: str
    created_at: datetime = Field(default_factory=utc_now)


class ToolCall(BaseModel):
    name: RobotCommandName
    arguments: dict[str, Any]


class RobotCommand(BaseModel):
    command_id: str = Field(default_factory=lambda: new_id("cmd"))
    session_id: str
    command_name: RobotCommandName
    correlation_id: str
    idempotency_key: str
    parameters: dict[str, Any]
    status: CommandStatus = CommandStatus.PENDING
    created_at: datetime = Field(default_factory=utc_now)


class DomainEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: new_id("evt"))
    event_type: str
    correlation_id: str
    session_id: str
    command_id: str | None = None
    occurred_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
