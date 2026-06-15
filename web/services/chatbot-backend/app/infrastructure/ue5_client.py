from __future__ import annotations

import logging
from typing import Any

import httpx

from app.domain.models import (
    CommandStatus,
    ProcessTelemetry,
    RobotCommand,
    RobotCommandName,
)

logger = logging.getLogger(__name__)

# Maps each AGV/sim command to the UE5 AGVSimController HTTP route on :7777.
_COMMAND_ROUTES: dict[RobotCommandName, str] = {
    RobotCommandName.START_SIMULATION: "/sim/start",
    RobotCommandName.STOP_SIMULATION: "/sim/stop",
    RobotCommandName.PAUSE_SIMULATION: "/sim/pause",
    RobotCommandName.RESUME_SIMULATION: "/sim/resume",
    RobotCommandName.SET_SIM_SPEED: "/sim/speed",
    RobotCommandName.MOVE_TO_STATION: "/agv/command",
    RobotCommandName.RUN_STATION_TASK: "/agv/command",
    RobotCommandName.INSPECT_STATION: "/agv/command",
    RobotCommandName.CANCEL_COMMAND: "/agv/command",
}


class Ue5CommandClient:
    """Drives the UE5 Virtual Process directly over the AGVSimController HTTP server.

    Implements both IotCommandClient (send_robot_command) and IotTelemetryClient
    (get_process_telemetry). UE5 echoes session_id/correlation_id/command_id back on
    its WebSocket event stream so the backend can route progress to the chat session.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def send_robot_command(self, command: RobotCommand) -> RobotCommand:
        route = _COMMAND_ROUTES.get(command.command_name)
        if route is None:
            logger.warning("No UE5 route for command %s", command.command_name)
            return command

        payload = {
            "command_id": command.command_id,
            "session_id": command.session_id,
            "correlation_id": command.correlation_id,
            "command_name": command.command_name.value,
            "idempotency_key": command.idempotency_key,
            "parameters": command.parameters,
        }
        try:
            response = await self._post(route, payload, command.correlation_id)
            response.raise_for_status()
            command.status = CommandStatus.ACCEPTED
        except httpx.HTTPError as exc:
            # UE5 unreachable: mark the command FAILED so the chat turn can tell the
            # operator the simulator never received it, instead of reporting success.
            logger.error(
                "UE5 command %s (%s) failed: %s",
                command.command_name,
                command.command_id,
                exc,
            )
            command.status = CommandStatus.FAILED
        return command

    async def select_camera(self, agv_id: str, correlation_id: str) -> bool:
        """Switch the UE5 viewport to an AGV's viewpoint camera (or 'overview')."""
        try:
            response = await self._post("/camera/select", {"agv_id": agv_id}, correlation_id)
            response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.error("UE5 camera select for %s failed: %s", agv_id, exc)
            return False

    async def start_simulation_run(
        self,
        run_id: str,
        parameters: dict[str, Any],
        correlation_id: str,
    ) -> bool:
        payload = {
            "run_id": run_id,
            "session_id": "simulation-control",
            "correlation_id": correlation_id,
            "command_id": run_id,
            "command_name": RobotCommandName.START_SIMULATION.value,
            "parameters": parameters,
        }
        return await self._control("/sim/start", payload, correlation_id)

    async def pause_simulation_run(self, run_id: str, correlation_id: str) -> bool:
        return await self._control(
            "/sim/pause",
            {"run_id": run_id, "session_id": "simulation-control", "correlation_id": correlation_id, "command_id": run_id},
            correlation_id,
        )

    async def resume_simulation_run(self, run_id: str, correlation_id: str) -> bool:
        return await self._control(
            "/sim/resume",
            {"run_id": run_id, "session_id": "simulation-control", "correlation_id": correlation_id, "command_id": run_id},
            correlation_id,
        )

    async def stop_simulation_run(self, run_id: str, correlation_id: str) -> bool:
        return await self._control(
            "/sim/stop",
            {"run_id": run_id, "session_id": "simulation-control", "correlation_id": correlation_id, "command_id": run_id},
            correlation_id,
        )

    async def set_simulation_speed(
        self,
        run_id: str,
        speed_multiplier: float,
        correlation_id: str,
    ) -> bool:
        return await self._control(
            "/sim/speed",
            {
                "run_id": run_id,
                "session_id": "simulation-control",
                "correlation_id": correlation_id,
                "command_id": run_id,
                "parameters": {"speed_multiplier": speed_multiplier},
            },
            correlation_id,
        )

    async def get_process_telemetry(self, correlation_id: str) -> ProcessTelemetry:
        try:
            response = await self._get("/sim/status", correlation_id)
            response.raise_for_status()
            data = response.json()
            max_agvs = data.get("max_agvs")
            return ProcessTelemetry(
                cell_id=data.get("cell_id", "cell_demo"),
                throughput=float(data.get("throughput", 0.0)),
                active_agvs=int(data.get("active_agvs", 0)),
                avg_wait_time=float(data.get("avg_wait_time", 0.0)),
                collision_risk=float(data.get("collision_risk", 0.0)),
                uptime=float(data.get("uptime", 0.0)),
                max_agvs=int(max_agvs) if max_agvs is not None else None,
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.warning("UE5 telemetry unavailable, returning zeros: %s", exc)
            return ProcessTelemetry(
                throughput=0.0,
                active_agvs=0,
                avg_wait_time=0.0,
                collision_risk=0.0,
                uptime=0.0,
            )

    async def _post(self, path: str, payload: dict, correlation_id: str) -> httpx.Response:
        headers = {"X-AGV-API-Key": self._api_key, "x-correlation-id": correlation_id}
        if self._client is not None:
            return await self._client.post(path, json=payload, headers=headers)
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout_seconds
        ) as client:
            return await client.post(path, json=payload, headers=headers)

    async def _control(self, path: str, payload: dict[str, Any], correlation_id: str) -> bool:
        try:
            response = await self._post(path, payload, correlation_id)
            response.raise_for_status()
            return True
        except httpx.HTTPError as exc:
            logger.error("UE5 control %s failed: %s", path, exc)
            return False

    async def _get(self, path: str, correlation_id: str) -> httpx.Response:
        headers = {"X-AGV-API-Key": self._api_key, "x-correlation-id": correlation_id}
        if self._client is not None:
            return await self._client.get(path, headers=headers)
        async with httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout_seconds
        ) as client:
            return await client.get(path, headers=headers)
