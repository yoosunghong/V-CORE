from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request, status

from app.domain import CellStatus, ControlEvent, ControlTask, Station
from app.repository import InMemoryControlRepository
from app.schemas import CreateTaskRequest, PublishEventRequest, UpdateTaskStatusRequest


def get_repository(request: Request) -> InMemoryControlRepository:
    return request.app.state.repository


def create_app() -> FastAPI:
    application = FastAPI(
        title="Virtual Process Control Server Demo",
        version="0.1.0",
        description="Virtual Process demo control server API (station registry) for chatbot integration.",
    )
    application.state.repository = InMemoryControlRepository()

    @application.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "control-server-demo"}

    @application.get("/cell/status", response_model=CellStatus, tags=["cell"])
    async def cell_status(
        repository: InMemoryControlRepository = Depends(get_repository),
    ) -> CellStatus:
        return await repository.cell_status()

    @application.get("/stations/{station_id}", response_model=Station, tags=["cell"])
    async def get_station(
        station_id: int,
        repository: InMemoryControlRepository = Depends(get_repository),
    ) -> Station:
        station = await repository.get_station(station_id)
        if station is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown station_id: {station_id}",
            )
        return station

    @application.post(
        "/tasks",
        response_model=ControlTask,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["tasks"],
    )
    async def create_task(
        request: CreateTaskRequest,
        repository: InMemoryControlRepository = Depends(get_repository),
    ) -> ControlTask:
        task = ControlTask(
            command_name=request.command_name,
            target_type=request.target_type,
            target_id=request.target_id,
            correlation_id=request.correlation_id,
            idempotency_key=request.idempotency_key,
            parameters=request.parameters,
        )
        return await repository.create_task(task)

    @application.get("/tasks/{task_id}", response_model=ControlTask, tags=["tasks"])
    async def get_task(
        task_id: str,
        repository: InMemoryControlRepository = Depends(get_repository),
    ) -> ControlTask:
        task = await repository.get_task(task_id)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown task_id: {task_id}",
            )
        return task

    @application.patch("/tasks/{task_id}", response_model=ControlTask, tags=["tasks"])
    async def update_task_status(
        task_id: str,
        request: UpdateTaskStatusRequest,
        repository: InMemoryControlRepository = Depends(get_repository),
    ) -> ControlTask:
        task = await repository.update_task_status(task_id, request.status)
        if task is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown task_id: {task_id}",
            )
        return task

    @application.post(
        "/events",
        response_model=ControlEvent,
        status_code=status.HTTP_202_ACCEPTED,
        tags=["events"],
    )
    async def publish_event(
        request: PublishEventRequest,
        repository: InMemoryControlRepository = Depends(get_repository),
    ) -> ControlEvent:
        event = ControlEvent(
            event_type=request.event_type,
            correlation_id=request.correlation_id,
            task_id=request.task_id,
            payload=request.payload,
        )
        return await repository.publish_event(event)

    @application.get("/events", response_model=list[ControlEvent], tags=["events"])
    async def list_events(
        repository: InMemoryControlRepository = Depends(get_repository),
    ) -> list[ControlEvent]:
        return await repository.list_events()

    return application


app = create_app()
