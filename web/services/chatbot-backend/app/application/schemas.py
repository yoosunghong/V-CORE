from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain.models import ChatMessage, CommandStatus, DomainEvent, SimulationRunStatus


class CreateSessionRequest(BaseModel):
    user_id: str | None = None
    unreal_client_id: str | None = None


class SessionResponse(BaseModel):
    session_id: str
    user_id: str | None
    unreal_client_id: str | None
    created_at: str | None = None


class SessionSummaryResponse(SessionResponse):
    message_count: int = 0
    last_message_at: str | None = None
    last_message_preview: str | None = None
    first_user_message_preview: str | None = None


class SessionListResponse(BaseModel):
    sessions: list[SessionSummaryResponse]


class SessionMessagesResponse(BaseModel):
    session_id: str
    messages: list[ChatMessage]


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str = Field(min_length=1, max_length=2000)
    user_id: str | None = None
    unreal_client_id: str | None = None
    idempotency_key: str | None = None


class ChatResponse(BaseModel):
    session_id: str
    correlation_id: str
    message: ChatMessage
    command_id: str | None = None
    status: CommandStatus | None = None
    events: list[DomainEvent] = Field(default_factory=list)


class SimulationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    agv_count: int = Field(default=3, ge=1, le=20)
    speed_multiplier: float = Field(default=1.0, ge=0.1, le=20.0)
    workload_percent: float = Field(default=100.0, ge=1.0, le=300.0)
    policy_id: str = Field(default="POLICY_FIFO", min_length=1, max_length=64)
    duration_seconds: int = Field(default=600, ge=10, le=86400)
    bottleneck_threshold_sec: float = Field(default=10.0, ge=0.1, le=3600.0)


class SimulationResponse(SimulationRequest):
    simulation_id: str
    created_at: str
    updated_at: str


class SimulationListResponse(BaseModel):
    simulations: list[SimulationResponse]


class DuplicateSimulationRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class RunResponse(BaseModel):
    run_id: str
    simulation_id: str
    status: SimulationRunStatus
    ue_run_id: str | None = None
    speed_multiplier: float
    started_at: str | None = None
    ended_at: str | None = None
    result_json: dict[str, Any] | None = None
    kpis_json: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class RunListResponse(BaseModel):
    runs: list[RunResponse]


class SpeedControlRequest(BaseModel):
    speed_multiplier: float = Field(ge=0.1, le=20.0)


class RunResultResponse(BaseModel):
    run: RunResponse
    live: dict[str, Any] | None = None


class CompletionEventRequest(BaseModel):
    event_type: str
    correlation_id: str
    session_id: str
    command_id: str
    payload: dict[str, Any] = Field(default_factory=dict)


class UnrealZoneFocusRequest(BaseModel):
    unreal_client_id: str = "ue-webview"
    idempotency_key: str | None = None


class UnrealZoneFocusResponse(BaseModel):
    status: str
    zone_id: str
    unreal_client_id: str
    command_id: str
    api_path: str
    issued_at: str


class UnrealViewportResponse(BaseModel):
    mode: str
    stream_url: str
    telemetry_sse_url: str
    transport: str = "pixel-streaming-webrtc"
    telemetry_transport: str = "sse"
    generated_at: str


class CameraSelectRequest(BaseModel):
    unreal_client_id: str = "ue-webview"
    idempotency_key: str | None = None


class CameraSelectResponse(BaseModel):
    status: str
    agv_id: str
    unreal_client_id: str
    command_id: str
    api_path: str
    issued_at: str


class OverlayZone(BaseModel):
    id: str
    name: str
    subtitle: str
    active: bool = False


class OverlayMetric(BaseModel):
    id: str
    title: str
    subtitle: str
    value: float
    unit: str
    trend_percent: float
    series: list[float] = Field(default_factory=list)


class OverlayWorkload(BaseModel):
    id: str
    title: str
    subtitle: str
    value: float
    unit: str
    status: str
    active: bool = False


class OverlayDashboardResponse(BaseModel):
    cell_id: str
    zones: list[OverlayZone]
    metrics: list[OverlayMetric]
    workloads: list[OverlayWorkload]
    command_feed: list[str]
    generated_at: str
