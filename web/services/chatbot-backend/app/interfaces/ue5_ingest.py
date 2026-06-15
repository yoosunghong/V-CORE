from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect, status

from app.domain.models import DomainEvent, SimulationRunStatus
from app.domain.process_model import bottleneck_rate_from_heatmap
from app.infrastructure.container import AppContainer

logger = logging.getLogger(__name__)

router = APIRouter()
ws_router = APIRouter()

# Completion events route through the chat orchestrator so a report message is produced.
_COMPLETION_EVENT_TYPES = {"robot.command.completed", "robot.command.failed"}

# UE5 telemetry frames (kind=agv|process) arrive on the same WebSocket as events but
# carry no event_type; they are forwarded to telemetry-collector over the in-Docker
# network because UE5 raw-socket UDP/TCP does not traverse the Windows proxy reliably.
_TELEMETRY_KINDS = {"agv", "process"}

_telemetry_http: httpx.AsyncClient | None = None
# Forwards are fired concurrently (not awaited inline) so a slow collector write
# never stalls the WebSocket receive loop and back-pressures the ~20 frames/s stream.
_forward_tasks: set[asyncio.Task[None]] = set()


def _telemetry_client() -> httpx.AsyncClient:
    global _telemetry_http
    if _telemetry_http is None:
        _telemetry_http = httpx.AsyncClient(timeout=2.0)
    return _telemetry_http


def _is_telemetry(payload: dict[str, Any]) -> bool:
    return not payload.get("event_type") and payload.get("kind") in _TELEMETRY_KINDS


async def _forward_telemetry(container: AppContainer, node: dict[str, Any]) -> None:
    url = f"{container.settings.telemetry_collector_url.rstrip('/')}/ingest"
    try:
        await _telemetry_client().post(url, json=node)
    except httpx.HTTPError as exc:
        logger.debug("Telemetry forward to collector failed: %s", exc)


def _to_domain_event(raw: dict[str, Any]) -> DomainEvent | None:
    session_id = raw.get("session_id")
    event_type = raw.get("event_type")
    if not session_id or not event_type:
        return None
    return DomainEvent(
        event_type=event_type,
        correlation_id=raw.get("correlation_id") or session_id,
        session_id=session_id,
        command_id=raw.get("command_id"),
        payload=raw.get("payload") or {},
    )


async def _ingest_event(container: AppContainer, raw: dict[str, Any]) -> None:
    event = _to_domain_event(raw)
    if event is None:
        return
    payload = event.payload or {}
    payload_run_id = payload.get("run_id")
    run_id = payload_run_id if isinstance(payload_run_id, str) else event.command_id
    updated_run = None
    if event.event_type in _COMPLETION_EVENT_TYPES and run_id:
        run = await container.repository.get_run(run_id)
        if run is None:
            run = next(
                (
                    candidate
                    for candidate in await container.repository.list_runs()
                    if candidate.ue_run_id == run_id
                ),
                None,
            )
        if run is not None:
            run_id = run.run_id
        status = (
            SimulationRunStatus.COMPLETED
            if event.event_type == "robot.command.completed"
            else SimulationRunStatus.FAILED
        )
        result_json = dict(payload)
        kpis = payload.get("kpis")
        # Derive the bottleneck rate from the run's congestion heatmap at the boundary, so every
        # real UE5 run carries it as a first-class KPI (UE5 emits the grid, not the rate). Mutating
        # the dict in place enriches both the stored run and the published completion event payload.
        if isinstance(kpis, dict) and "bottleneck_rate" not in kpis and kpis.get("heatmap_grid"):
            kpis["bottleneck_rate"] = bottleneck_rate_from_heatmap(
                kpis.get("heatmap_grid") or [],
                int(kpis.get("heatmap_res_x") or 0),
                int(kpis.get("heatmap_res_y") or 0),
                kpis.get("heatmap_traversed_grid"),
            )
        updated_run = await container.repository.update_run_status(
            run_id,
            status,
            result_json=result_json,
            kpis_json=kpis if isinstance(kpis, dict) else None,
        )
        if updated_run is not None:
            await container.events.publish(
                DomainEvent(
                    event_type="simulation.run.updated",
                    correlation_id=event.correlation_id,
                    session_id=event.session_id,
                    command_id=event.command_id,
                    payload={
                        "simulation_id": updated_run.simulation_id,
                        "run_id": updated_run.run_id,
                        "status": updated_run.status,
                        "speed_multiplier": updated_run.speed_multiplier,
                        "source": "ue5",
                    },
                )
            )
    # Completion/failure events are handled by the orchestrator, which updates the
    # command, publishes the event, and emits a chat report. Other progress events
    # (robot.moving, robot.working, sim.progress, ...) are published directly.
    if event.event_type in _COMPLETION_EVENT_TYPES and event.command_id:
        try:
            await container.chat.handle_completion_event(event)
            return
        except ValueError:
            logger.warning("UE5 completion for unknown command %s", event.command_id)
    await container.events.publish(event)


def _authorized(container: AppContainer, provided_key: str | None) -> bool:
    expected = container.settings.agv_api_key
    return provided_key == expected


@router.post("/internal/ue5/events", tags=["internal"])
async def receive_ue5_event(request: Request) -> dict[str, str]:
    container: AppContainer = request.app.state.container
    if not _authorized(container, request.headers.get("x-agv-api-key")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid AGV API key")
    raw = await request.json()
    await _ingest_event(container, raw)
    return {"status": "received"}


@ws_router.websocket("/internal/ue5/stream")
async def ue5_stream(websocket: WebSocket) -> None:
    container: AppContainer = websocket.app.state.container
    provided_key = websocket.query_params.get("api_key") or websocket.headers.get("x-agv-api-key")
    if not _authorized(container, provided_key):
        await websocket.close(code=4403, reason="Invalid AGV API key")
        return
    await websocket.accept()
    try:
        async for raw_text in websocket.iter_text():
            try:
                payload = json.loads(raw_text)
            except ValueError:
                continue  # skip heartbeats / malformed frames
            if not isinstance(payload, dict):
                continue
            if _is_telemetry(payload):
                # Cache for the SSE live feed (Firebase-independent), then fan out to the
                # collector for the Firebase secondary path.
                container.live_telemetry.ingest(payload)
                task = asyncio.create_task(_forward_telemetry(container, payload))
                _forward_tasks.add(task)
                task.add_done_callback(_forward_tasks.discard)
            else:
                await _ingest_event(container, payload)
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
