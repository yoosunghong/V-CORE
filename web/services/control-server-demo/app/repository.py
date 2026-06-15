from __future__ import annotations

from app.domain import (
    CellStatus,
    ControlEvent,
    ControlTask,
    ProcessTelemetry,
    Station,
    TaskStatus,
    utc_now,
)


class InMemoryControlRepository:
    def __init__(self) -> None:
        self._stations: dict[int, Station] = {
            1: Station(
                station_id=1,
                station_type="loading",
                task_ready=False,
                zone="A",
                state="idle",
            ),
            2: Station(
                station_id=2,
                station_type="work",
                task_ready=True,
                zone="A",
                state="task_ready",
            ),
            3: Station(
                station_id=3,
                station_type="inspection",
                task_ready=False,
                zone="B",
                state="idle",
            ),
            4: Station(
                station_id=4,
                station_type="unloading",
                task_ready=True,
                zone="B",
                state="task_ready",
                accessible=False,
            ),
        }
        self._tasks: dict[str, ControlTask] = {}
        self._idempotency_index: dict[str, str] = {}
        self._events: list[ControlEvent] = []

    async def cell_status(self) -> CellStatus:
        return CellStatus(
            cell_id="cell_demo",
            stations=list(self._stations.values()),
            telemetry=ProcessTelemetry(
                throughput=68.2,
                active_agvs=3,
                avg_wait_time=12.0,
                collision_risk=0.0,
                uptime=0.97,
            ),
        )

    async def get_station(self, station_id: int) -> Station | None:
        return self._stations.get(station_id)

    async def create_task(self, task: ControlTask) -> ControlTask:
        existing_task_id = self._idempotency_index.get(task.idempotency_key)
        if existing_task_id:
            return self._tasks[existing_task_id]
        self._tasks[task.task_id] = task
        self._idempotency_index[task.idempotency_key] = task.task_id
        return task

    async def get_task(self, task_id: str) -> ControlTask | None:
        return self._tasks.get(task_id)

    async def update_task_status(self, task_id: str, status: TaskStatus) -> ControlTask | None:
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.status = status
        task.updated_at = utc_now()
        return task

    async def publish_event(self, event: ControlEvent) -> ControlEvent:
        self._events.append(event)
        if event.task_id and event.event_type.endswith(".completed"):
            await self.update_task_status(event.task_id, TaskStatus.COMPLETED)
        if event.task_id and event.event_type.endswith(".failed"):
            await self.update_task_status(event.task_id, TaskStatus.FAILED)
        return event

    async def list_events(self) -> list[ControlEvent]:
        return list(self._events)
