import asyncio

import httpx

from app.domain.models import CommandStatus, ProcessTelemetry, RobotCommand, RobotCommandName
from app.infrastructure.ue5_client import Ue5CommandClient


def test_ue5_client_posts_sim_start_to_ue5() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sim/start"
        assert request.headers["X-AGV-API-Key"] == "test-key"
        return httpx.Response(202, json={"status": "accepted"})

    async def run() -> RobotCommand:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://ue5.test") as client:
            ue5 = Ue5CommandClient(base_url="http://ue5.test", api_key="test-key", client=client)
            return await ue5.send_robot_command(
                RobotCommand(
                    command_id="cmd_ue5",
                    session_id="session_ue5",
                    command_name=RobotCommandName.START_SIMULATION,
                    correlation_id="corr_ue5",
                    idempotency_key="idem-ue5",
                    parameters={"agv_count": 3, "speed_multiplier": 1.0},
                )
            )

    command = asyncio.run(run())
    assert command.status == CommandStatus.ACCEPTED


def test_ue5_client_confirms_stop_completed_after_accepted_response() -> None:
    status_checks = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal status_checks
        if request.url.path == "/sim/stop":
            return httpx.Response(202, json={"status": "accepted"})
        assert request.url.path == "/sim/status"
        status_checks += 1
        return httpx.Response(200, json={"running": status_checks < 2})

    async def run() -> RobotCommand:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://ue5.test") as client:
            ue5 = Ue5CommandClient(
                base_url="http://ue5.test",
                api_key="test-key",
                client=client,
                stop_verify_attempts=2,
                stop_verify_interval_seconds=0,
            )
            return await ue5.send_robot_command(
                RobotCommand(
                    command_id="cmd_stop",
                    session_id="session_ue5",
                    command_name=RobotCommandName.STOP_SIMULATION,
                    correlation_id="corr_stop",
                    idempotency_key="idem-stop",
                    parameters={},
                )
            )

    command = asyncio.run(run())
    assert status_checks == 2
    assert command.status == CommandStatus.ACCEPTED


def test_ue5_client_marks_stop_failed_when_simulation_keeps_running() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sim/stop":
            return httpx.Response(202, json={"status": "accepted"})
        return httpx.Response(200, json={"running": True})

    async def run() -> RobotCommand:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://ue5.test") as client:
            ue5 = Ue5CommandClient(
                base_url="http://ue5.test",
                api_key="test-key",
                client=client,
                stop_verify_attempts=2,
                stop_verify_interval_seconds=0,
            )
            return await ue5.send_robot_command(
                RobotCommand(
                    command_id="cmd_stop_stuck",
                    session_id="session_ue5",
                    command_name=RobotCommandName.STOP_SIMULATION,
                    correlation_id="corr_stop_stuck",
                    idempotency_key="idem-stop-stuck",
                    parameters={},
                )
            )

    command = asyncio.run(run())
    assert command.status == CommandStatus.FAILED


def test_ue5_client_maps_status_to_process_telemetry() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/sim/status"
        return httpx.Response(
            200,
            json={
                "cell_id": "cell_demo",
                "throughput": 70.0,
                "active_agvs": 3,
                "avg_wait_time": 11.0,
                "collision_risk": 0.0,
                "uptime": 0.95,
            },
        )

    async def run() -> ProcessTelemetry:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://ue5.test") as client:
            ue5 = Ue5CommandClient(base_url="http://ue5.test", api_key="test-key", client=client)
            return await ue5.get_process_telemetry("corr_status")

    telemetry = asyncio.run(run())
    assert telemetry.throughput == 70.0
    assert telemetry.active_agvs == 3


def test_ue5_client_telemetry_falls_back_when_ue5_unreachable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no UE5")

    async def run() -> ProcessTelemetry:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://ue5.test") as client:
            ue5 = Ue5CommandClient(base_url="http://ue5.test", api_key="test-key", client=client)
            return await ue5.get_process_telemetry("corr_status")

    telemetry = asyncio.run(run())
    assert telemetry.throughput == 0.0
    assert telemetry.active_agvs == 0
