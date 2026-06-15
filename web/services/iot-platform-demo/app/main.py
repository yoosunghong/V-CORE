from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, status

from app.domain import Actuator, IotEvent, Robot, RobotCommand, SensorSnapshot
from app.repository import InMemoryIotRepository
from app.schemas import RobotCommandRequest, SetActuatorStatusRequest, SimulateFailureRequest


def get_repository(request: Request) -> InMemoryIotRepository:
    return request.app.state.repository


def create_app() -> FastAPI:
    application = FastAPI(
        title="PAI IoT Platform Demo",
        version="0.1.0",
        description="Smart farm IoT platform mock for robot, sensor, and digital-twin events.",
    )
    application.state.repository = InMemoryIotRepository()

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "iot-platform-demo"}

    @application.get("/robots", response_model=list[Robot], tags=["robots"])
    async def list_robots(
        repository: InMemoryIotRepository = Depends(get_repository),
    ) -> list[Robot]:
        return await repository.list_robots()

    @application.get("/robots/{robot_id}", response_model=Robot, tags=["robots"])
    async def get_robot(
        robot_id: str,
        repository: InMemoryIotRepository = Depends(get_repository),
    ) -> Robot:
        robot = await repository.get_robot(robot_id)
        if robot is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown robot_id: {robot_id}",
            )
        return robot

    @application.post(
        "/robots/commands",
        response_model=RobotCommand,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["robots"],
    )
    async def receive_robot_command(
        request: RobotCommandRequest,
        repository: InMemoryIotRepository = Depends(get_repository),
    ) -> RobotCommand:
        command = RobotCommand(
            command_id=request.command_id,
            session_id=request.session_id,
            command_name=request.command_name,
            correlation_id=request.correlation_id,
            idempotency_key=request.idempotency_key,
            parameters=request.parameters,
        )
        return await repository.accept_command(command)

    @application.get(
        "/robots/commands/{command_id}",
        response_model=RobotCommand,
        tags=["robots"],
    )
    async def get_robot_command(
        command_id: str,
        repository: InMemoryIotRepository = Depends(get_repository),
    ) -> RobotCommand:
        command = await repository.get_command(command_id)
        if command is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown command_id: {command_id}",
            )
        return command

    @application.post(
        "/robots/commands/{command_id}/simulate-failure",
        response_model=RobotCommand,
        tags=["robots"],
    )
    async def simulate_command_failure(
        command_id: str,
        request: SimulateFailureRequest,
        repository: InMemoryIotRepository = Depends(get_repository),
    ) -> RobotCommand:
        command = await repository.fail_command(command_id, request.reason)
        if command is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown command_id: {command_id}",
            )
        return command

    @application.get("/sensors/snapshot", response_model=SensorSnapshot, tags=["sensors"])
    async def sensor_snapshot(
        repository: InMemoryIotRepository = Depends(get_repository),
    ) -> SensorSnapshot:
        return await repository.sensor_snapshot()

    @application.get("/actuators", response_model=list[Actuator], tags=["actuators"])
    async def list_actuators(
        repository: InMemoryIotRepository = Depends(get_repository),
    ) -> list[Actuator]:
        return await repository.list_actuators()

    @application.patch(
        "/actuators/{actuator_id}",
        response_model=Actuator,
        tags=["actuators"],
    )
    async def set_actuator_status(
        actuator_id: str,
        request: SetActuatorStatusRequest,
        repository: InMemoryIotRepository = Depends(get_repository),
    ) -> Actuator:
        actuator = await repository.set_actuator_status(actuator_id, request.status)
        if actuator is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown actuator_id: {actuator_id}",
            )
        return actuator

    @application.get("/digital-twin/events", response_model=list[IotEvent], tags=["events"])
    async def list_digital_twin_events(
        repository: InMemoryIotRepository = Depends(get_repository),
    ) -> list[IotEvent]:
        return await repository.list_events()

    @application.websocket("/digital-twin/events")
    async def digital_twin_events(websocket: WebSocket) -> None:
        await websocket.accept()
        repository: InMemoryIotRepository = websocket.app.state.repository
        for event in await repository.list_events():
            await websocket.send_json(event.model_dump(mode="json"))
        await websocket.close()

    return application


app = create_app()
