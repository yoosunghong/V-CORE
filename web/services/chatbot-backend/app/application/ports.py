from __future__ import annotations

from typing import Protocol

from app.domain.models import (
    ChatMessage,
    ChatSession,
    ChatSessionSummary,
    DomainEvent,
    ProcessTelemetry,
    RetrievedChunk,
    RobotCommand,
    SimulationRun,
    SimulationRunStatus,
    Simulation,
    Station,
    ToolCall,
)


class SessionRepository(Protocol):
    async def create(self, session: ChatSession) -> ChatSession: ...
    async def get(self, session_id: str) -> ChatSession | None: ...
    async def delete(self, session_id: str) -> None: ...
    async def list_sessions(
        self,
        user_id: str | None = None,
        unreal_client_id: str | None = None,
        limit: int = 20,
    ) -> list[ChatSessionSummary]: ...
    async def add_message(self, message: ChatMessage) -> ChatMessage: ...
    async def list_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[ChatMessage]: ...
    async def list_commands(self, session_id: str) -> list[RobotCommand]: ...
    async def save_command(self, command: RobotCommand) -> RobotCommand: ...
    async def get_command(self, command_id: str) -> RobotCommand | None: ...
    async def get_command_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> RobotCommand | None: ...
    async def update_command(self, command: RobotCommand) -> RobotCommand: ...
    async def list_simulations(self) -> list[Simulation]: ...
    async def create_simulation(self, simulation: Simulation) -> Simulation: ...
    async def get_simulation(self, simulation_id: str) -> Simulation | None: ...
    async def update_simulation(self, simulation: Simulation) -> Simulation: ...
    async def delete_simulation(self, simulation_id: str) -> None: ...
    async def create_run(self, run: SimulationRun) -> SimulationRun: ...
    async def get_run(self, run_id: str) -> SimulationRun | None: ...
    async def list_runs(self, simulation_id: str | None = None) -> list[SimulationRun]: ...
    async def update_run(self, run: SimulationRun) -> SimulationRun: ...
    async def update_run_status(
        self,
        run_id: str,
        status: SimulationRunStatus,
        result_json: dict | None = None,
        kpis_json: dict | None = None,
    ) -> SimulationRun | None: ...


class EventPublisher(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...


class KnowledgeGateway(Protocol):
    async def retrieve(
        self,
        query: str,
        correlation_id: str,
        *,
        top_k: int = 5,
        filters: dict[str, str] | None = None,
    ) -> list[RetrievedChunk]: ...


class ControlServerClient(Protocol):
    async def get_station(self, station_id: int, correlation_id: str) -> Station: ...
    async def list_stations(self, correlation_id: str) -> list[Station]: ...


class IotCommandClient(Protocol):
    async def send_robot_command(self, command: RobotCommand) -> RobotCommand: ...


class IotTelemetryClient(Protocol):
    async def get_process_telemetry(self, correlation_id: str) -> ProcessTelemetry: ...


class LlmGateway(Protocol):
    async def classify_intent(
        self,
        user_message: str,
        correlation_id: str,
    ) -> str | None: ...

    async def generate_plan_steps(
        self,
        user_message: str,
        correlation_id: str,
    ) -> list[str]: ...

    async def propose_tool_call(
        self,
        user_message: str,
        station: Station | None,
        correlation_id: str,
    ) -> ToolCall | None: ...

    async def generate_report(
        self,
        event: DomainEvent,
        command: RobotCommand,
        correlation_id: str,
        evaluation: str | None = None,
        knowledge: list[RetrievedChunk] | None = None,
    ) -> str: ...

    async def generate_chat_response(
        self,
        user_message: str,
        history: list[dict[str, str]],
        correlation_id: str,
        knowledge: list[RetrievedChunk] | None = None,
    ) -> str: ...
