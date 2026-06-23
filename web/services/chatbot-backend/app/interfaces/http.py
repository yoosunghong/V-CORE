from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from app.application.schemas import (
    CameraSelectRequest,
    CameraSelectResponse,
    ChatRequest,
    ChatResponse,
    CompletionEventRequest,
    CreateSessionRequest,
    DuplicateSimulationRequest,
    OverlayDashboardResponse,
    OverlayMetric,
    OverlayWorkload,
    OverlayZone,
    RunListResponse,
    RunResponse,
    RunResultResponse,
    SimulationListResponse,
    SimulationRequest,
    SimulationResponse,
    SessionListResponse,
    SessionMessagesResponse,
    SessionResponse,
    SessionSummaryResponse,
    SpeedControlRequest,
    UnrealViewportResponse,
    UnrealZoneFocusRequest,
    UnrealZoneFocusResponse,
)
from app.domain.models import (
    DomainEvent,
    SimulationRun,
    SimulationRunStatus,
    Simulation,
    new_id,
    utc_now,
)
from app.infrastructure.container import AppContainer
from app.interfaces.dependencies import get_container

router = APIRouter()


def _truncate_text(value: str | None, max_chars: int) -> str | None:
    if value is None or len(value) <= max_chars:
        return value
    return f"{value[: max(max_chars - 1, 0)]}..."


def _simulation_response(simulation: Simulation) -> SimulationResponse:
    return SimulationResponse(
        simulation_id=simulation.simulation_id,
        name=simulation.name,
        agv_count=simulation.agv_count,
        speed_multiplier=simulation.speed_multiplier,
        workload_percent=simulation.workload_percent,
        policy_id=simulation.policy_id,
        duration_seconds=simulation.duration_seconds,
        bottleneck_threshold_sec=simulation.bottleneck_threshold_sec,
        created_at=simulation.created_at.isoformat(),
        updated_at=simulation.updated_at.isoformat(),
    )


def _run_response(run: SimulationRun) -> RunResponse:
    return RunResponse(
        run_id=run.run_id,
        simulation_id=run.simulation_id,
        status=run.status,
        ue_run_id=run.ue_run_id,
        speed_multiplier=run.speed_multiplier,
        started_at=run.started_at.isoformat() if run.started_at else None,
        ended_at=run.ended_at.isoformat() if run.ended_at else None,
        result_json=run.result_json,
        kpis_json=run.kpis_json,
        created_at=run.created_at.isoformat(),
        updated_at=run.updated_at.isoformat(),
    )


def _simulation_from_request(request: SimulationRequest, simulation_id: str | None = None) -> Simulation:
    values = request.model_dump()
    if simulation_id is not None:
        values["simulation_id"] = simulation_id
    return Simulation(**values)


def _simulation_parameters(simulation: Simulation) -> dict[str, Any]:
    return {
        "agv_count": simulation.agv_count,
        "speed_multiplier": simulation.speed_multiplier,
        "duration": simulation.duration_seconds,
        "policy_id": simulation.policy_id,
        "bottleneck_threshold_sec": simulation.bottleneck_threshold_sec,
        "workload_percent": simulation.workload_percent,
    }


def _telemetry_kpis(telemetry: Any) -> dict[str, Any]:
    return {
        "throughput": telemetry.throughput,
        "active_agvs": telemetry.active_agvs,
        "avg_wait_time": telemetry.avg_wait_time,
        "collision_risk": telemetry.collision_risk,
        "uptime": telemetry.uptime,
        "measured_at": telemetry.measured_at.isoformat(),
    }


async def _live_snapshot(container: AppContainer) -> dict[str, Any]:
    telemetry = await container.iot_client.get_process_telemetry(new_id("corr_status"))
    return _telemetry_kpis(telemetry)


async def _proxy_control(
    container: AppContainer,
    method_name: str,
    *args: Any,
) -> bool:
    method = getattr(container.iot_client, method_name, None)
    if method is None:
        return True
    return bool(await method(*args))


@router.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "chatbot-backend"}


@router.get("/llm/status", tags=["system"])
async def llm_status(container: AppContainer = Depends(get_container)) -> dict[str, Any]:
    return dict(container.llm_status)


@router.get("/dashboard/overlay", response_model=OverlayDashboardResponse, tags=["dashboard"])
async def dashboard_overlay() -> OverlayDashboardResponse:
    return OverlayDashboardResponse(
        cell_id="VP-CELL-048-ALPHA",
        generated_at=datetime.now(UTC).isoformat(),
        zones=[
            OverlayZone(id="zone-1", name="ZONE 1", subtitle="AGV cell - main view", active=True),
            OverlayZone(id="zone-2", name="ZONE 2", subtitle="AGV cell - work"),
            OverlayZone(id="zone-3", name="ZONE 3", subtitle="AGV cell - unloading"),
        ],
        metrics=[
            OverlayMetric(
                id="throughput",
                title="Throughput",
                subtitle="Tasks per hour",
                value=68.2,
                unit="/h",
                trend_percent=2.1,
                series=[8, 9, 10, 24, 31, 36, 45, 52],
            ),
            OverlayMetric(
                id="uptime",
                title="Uptime",
                subtitle="Availability",
                value=97.0,
                unit="%",
                trend_percent=2.1,
                series=[18, 19, 21, 22, 24, 25, 27, 30],
            ),
            OverlayMetric(
                id="avg-wait-time",
                title="Avg Wait Time",
                subtitle="Queue delay",
                value=12.0,
                unit="s",
                trend_percent=2.1,
                series=[52, 51, 54, 55, 58, 56, 59, 61],
            ),
            OverlayMetric(
                id="collision-risk",
                title="Collision Risk",
                subtitle="Risk events",
                value=0.0,
                unit="/h",
                trend_percent=2.1,
                series=[20, 21, 21, 22, 23, 22, 23, 24],
            ),
            OverlayMetric(
                id="active-agvs",
                title="Active AGVs",
                subtitle="Fleet size",
                value=3.0,
                unit="",
                trend_percent=2.1,
                series=[12, 20, 30, 42, 54, 68, 76, 87],
            ),
        ],
        workloads=[
            OverlayWorkload(id="loading", title="Loading", subtitle="Load", value=0.0, unit="%", status="READY", active=True),
            OverlayWorkload(id="working", title="Working", subtitle="Work", value=0.0, unit="%", status="WAITING"),
            OverlayWorkload(id="unloading", title="Unloading", subtitle="Unload", value=0.0, unit="%", status="WAITING"),
        ],
        command_feed=[
            "Waiting for AGV telemetry.",
            "Use simulation playback controls to run the cell.",
            "Chat commands are routed through LangGraph tools.",
        ],
    )


@router.get("/unreal/viewport", response_model=UnrealViewportResponse, tags=["unreal"])
async def unreal_viewport(container: AppContainer = Depends(get_container)) -> UnrealViewportResponse:
    return UnrealViewportResponse(
        mode=container.settings.ue5_client_mode,
        stream_url=container.settings.ue5_view_url,
        telemetry_sse_url="/unreal/telemetry/stream",
        generated_at=datetime.now(UTC).isoformat(),
    )


@router.get("/unreal/telemetry/stream", tags=["unreal"])
async def unreal_telemetry_stream(
    once: bool = False,
    container: AppContainer = Depends(get_container),
) -> StreamingResponse:
    def _sse(event: str, data: Any) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    async def events():
        while True:
            hub = container.live_telemetry
            if hub.has_live_data():
                # Live UE5 frames (AGV list, process snapshot, HUD) relayed over the backend
                # WebSocket — the Firebase-independent path that drives the overlay + web HUD.
                yield _sse("agvs", hub.agvs())
                yield _sse("process", hub.process())
                yield _sse("hud", hub.hud())
            else:
                # No live sim. UE5 emits no terminal frame when a run ends — it simply
                # stops streaming — so without these explicit resets the overlay freezes
                # on the last live frame (e.g. HUD stuck on "RUNNING 25%"). Push empty/idle
                # frames so the AGV list, the running flag, and the HUD all return to idle,
                # then fall back to the IoT mock so the metric cards still render.
                yield _sse("agvs", [])
                yield _sse("process", {"running": False, "paused": False})
                yield _sse("hud", None)
                telemetry = await container.iot_client.get_process_telemetry("corr_unreal_sse")
                yield _sse("telemetry", telemetry.model_dump(mode="json"))
            if once:
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/unreal/zones/{zone_id}/focus",
    response_model=UnrealZoneFocusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["unreal"],
)
async def focus_unreal_zone(zone_id: str, request: UnrealZoneFocusRequest) -> UnrealZoneFocusResponse:
    if zone_id not in {"zone-1", "zone-2", "zone-3"}:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown Unreal zone: {zone_id}")
    return UnrealZoneFocusResponse(
        status="accepted",
        zone_id=zone_id,
        unreal_client_id=request.unreal_client_id,
        command_id=new_id("uecmd"),
        api_path=f"/digital-twin/zones/{zone_id}/focus",
        issued_at=datetime.now(UTC).isoformat(),
    )


@router.post(
    "/unreal/cameras/{agv_id}/select",
    response_model=CameraSelectResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["unreal"],
)
async def select_unreal_camera(
    agv_id: str,
    request: CameraSelectRequest,
    container: AppContainer = Depends(get_container),
) -> CameraSelectResponse:
    correlation_id = new_id("corr_camera")
    select = getattr(container.iot_client, "select_camera", None)
    if select is not None:
        await select(agv_id, correlation_id)
    return CameraSelectResponse(
        status="accepted",
        agv_id=agv_id,
        unreal_client_id=request.unreal_client_id,
        command_id=new_id("uecmd"),
        api_path="/camera/select",
        issued_at=datetime.now(UTC).isoformat(),
    )


@router.get("/api/v1/simulations", response_model=SimulationListResponse, tags=["simulations"])
async def list_simulations(container: AppContainer = Depends(get_container)) -> SimulationListResponse:
    simulations = await container.repository.list_simulations()
    if not simulations:
        baseline = Simulation(name="Baseline AGV cell", agv_count=3, speed_multiplier=1.0)
        simulations = [await container.repository.create_simulation(baseline)]
    return SimulationListResponse(simulations=[_simulation_response(item) for item in simulations])


@router.post(
    "/api/v1/simulations",
    response_model=SimulationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["simulations"],
)
async def create_simulation(
    request: SimulationRequest,
    container: AppContainer = Depends(get_container),
) -> SimulationResponse:
    simulation = await container.repository.create_simulation(_simulation_from_request(request))
    return _simulation_response(simulation)


@router.put("/api/v1/simulations/{simulation_id}", response_model=SimulationResponse, tags=["simulations"])
async def update_simulation(
    simulation_id: str,
    request: SimulationRequest,
    container: AppContainer = Depends(get_container),
) -> SimulationResponse:
    existing = await container.repository.get_simulation(simulation_id)
    if existing is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found")
    simulation = _simulation_from_request(request, simulation_id=simulation_id)
    simulation.created_at = existing.created_at
    simulation.updated_at = utc_now()
    return _simulation_response(await container.repository.update_simulation(simulation))


@router.delete("/api/v1/simulations/{simulation_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["simulations"])
async def delete_simulation(simulation_id: str, container: AppContainer = Depends(get_container)) -> None:
    if await container.repository.get_simulation(simulation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found")
    await container.repository.delete_simulation(simulation_id)


@router.post(
    "/api/v1/simulations/{simulation_id}/duplicate",
    response_model=SimulationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["simulations"],
)
async def duplicate_simulation(
    simulation_id: str,
    request: DuplicateSimulationRequest,
    container: AppContainer = Depends(get_container),
) -> SimulationResponse:
    source = await container.repository.get_simulation(simulation_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found")
    clone = source.model_copy(
        update={
            "simulation_id": new_id("simulation"),
            "name": request.name or f"{source.name} Copy",
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
    )
    return _simulation_response(await container.repository.create_simulation(clone))


@router.post("/api/v1/simulations/{simulation_id}/run", response_model=RunResponse, tags=["simulations"])
async def run_simulation(simulation_id: str, container: AppContainer = Depends(get_container)) -> RunResponse:
    simulation = await container.repository.get_simulation(simulation_id)
    if simulation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found")
    now = utc_now()
    run = await container.repository.create_run(
        SimulationRun(
            simulation_id=simulation.simulation_id,
            status=SimulationRunStatus.STARTING,
            speed_multiplier=simulation.speed_multiplier,
            started_at=now,
        )
    )
    correlation_id = new_id("corr_run")
    accepted = await _proxy_control(
        container,
        "start_simulation_run",
        run.run_id,
        _simulation_parameters(simulation),
        correlation_id,
    )
    run.status = SimulationRunStatus.RUNNING if accepted else SimulationRunStatus.FAILED
    run.ue_run_id = run.run_id
    if not accepted:
        run.ended_at = utc_now()
    return _run_response(await container.repository.update_run(run))


@router.get("/api/v1/simulations/{simulation_id}/runs", response_model=RunListResponse, tags=["simulations"])
async def list_simulation_runs(
    simulation_id: str,
    container: AppContainer = Depends(get_container),
) -> RunListResponse:
    if await container.repository.get_simulation(simulation_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Simulation not found")
    runs = await container.repository.list_runs(simulation_id)
    return RunListResponse(runs=[_run_response(item) for item in runs])


@router.post("/api/v1/runs/{run_id}/pause", response_model=RunResponse, tags=["runs"])
async def pause_run(run_id: str, container: AppContainer = Depends(get_container)) -> RunResponse:
    run = await container.repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await _proxy_control(container, "pause_simulation_run", run_id, new_id("corr_pause"))
    run.status = SimulationRunStatus.PAUSED
    return _run_response(await container.repository.update_run(run))


@router.post("/api/v1/runs/{run_id}/resume", response_model=RunResponse, tags=["runs"])
async def resume_run(run_id: str, container: AppContainer = Depends(get_container)) -> RunResponse:
    run = await container.repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await _proxy_control(container, "resume_simulation_run", run_id, new_id("corr_resume"))
    run.status = SimulationRunStatus.RUNNING
    return _run_response(await container.repository.update_run(run))


@router.post("/api/v1/runs/{run_id}/stop", response_model=RunResponse, tags=["runs"])
async def stop_run(run_id: str, container: AppContainer = Depends(get_container)) -> RunResponse:
    run = await container.repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    live = await _live_snapshot(container)
    await _proxy_control(container, "stop_simulation_run", run_id, new_id("corr_stop"))
    run.status = SimulationRunStatus.STOPPED
    run.ended_at = utc_now()
    run.result_json = {"stop_reason": "STOP_COMMAND", "live_snapshot": live}
    run.kpis_json = live
    return _run_response(await container.repository.update_run(run))


@router.post("/api/v1/runs/{run_id}/speed", response_model=RunResponse, tags=["runs"])
async def set_run_speed(
    run_id: str,
    request: SpeedControlRequest,
    container: AppContainer = Depends(get_container),
) -> RunResponse:
    run = await container.repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    await _proxy_control(
        container,
        "set_simulation_speed",
        run_id,
        request.speed_multiplier,
        new_id("corr_speed"),
    )
    run.speed_multiplier = request.speed_multiplier
    return _run_response(await container.repository.update_run(run))


@router.get("/api/v1/runs/{run_id}/result", response_model=RunResultResponse, tags=["runs"])
async def get_run_result(
    run_id: str,
    container: AppContainer = Depends(get_container),
) -> RunResultResponse:
    run = await container.repository.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    live = None if run.kpis_json else await _live_snapshot(container)
    return RunResultResponse(run=_run_response(run), live=live)


@router.post(
    "/chat/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["chat"],
)
async def create_session(
    request: CreateSessionRequest,
    container: AppContainer = Depends(get_container),
) -> SessionResponse:
    session = await container.sessions.create_session(
        user_id=request.user_id,
        unreal_client_id=request.unreal_client_id,
    )
    return SessionResponse(
        session_id=session.session_id,
        user_id=session.user_id,
        unreal_client_id=session.unreal_client_id,
        created_at=session.created_at.isoformat(),
    )


@router.get("/chat/sessions", response_model=SessionListResponse, tags=["chat"])
async def list_sessions(
    user_id: str | None = None,
    unreal_client_id: str | None = None,
    limit: int = 20,
    container: AppContainer = Depends(get_container),
) -> SessionListResponse:
    bounded_limit = min(max(limit, 1), 50)
    preview_max_chars = max(container.settings.session_preview_max_chars, 20)
    sessions = await container.sessions.list_sessions(
        user_id=user_id,
        unreal_client_id=unreal_client_id,
        limit=bounded_limit,
    )
    return SessionListResponse(
        sessions=[
            SessionSummaryResponse(
                session_id=session.session_id,
                user_id=session.user_id,
                unreal_client_id=session.unreal_client_id,
                created_at=session.created_at.isoformat(),
                message_count=session.message_count,
                last_message_at=session.last_message_at.isoformat()
                if session.last_message_at
                else None,
                last_message_preview=_truncate_text(session.last_message_preview, preview_max_chars),
                first_user_message_preview=_truncate_text(
                    session.first_user_message_preview,
                    preview_max_chars,
                ),
            )
            for session in sessions
        ]
    )


@router.get(
    "/chat/sessions/{session_id}/messages",
    response_model=SessionMessagesResponse,
    tags=["chat"],
)
async def list_session_messages(
    session_id: str,
    limit: int | None = None,
    max_content_chars: int | None = None,
    container: AppContainer = Depends(get_container),
) -> SessionMessagesResponse:
    effective_limit = limit if limit is not None else container.settings.session_history_limit
    bounded_limit = min(max(effective_limit, 1), 200)
    effective_max_chars = (
        max_content_chars
        if max_content_chars is not None
        else container.settings.session_history_message_max_chars
    )
    bounded_max_chars = min(max(effective_max_chars, 80), 8000)
    try:
        messages = await container.sessions.list_messages(session_id, limit=bounded_limit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    messages = [
        message.model_copy(
            update={"content": _truncate_text(message.content, bounded_max_chars) or ""}
        )
        for message in messages
    ]
    return SessionMessagesResponse(session_id=session_id, messages=messages)


@router.delete(
    "/chat/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["chat"],
)
async def delete_session(
    session_id: str,
    container: AppContainer = Depends(get_container),
) -> None:
    try:
        await container.sessions.delete_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/chat/messages", response_model=ChatResponse, tags=["chat"])
async def post_chat_message(
    request: ChatRequest,
    x_correlation_id: str | None = Header(default=None),
    container: AppContainer = Depends(get_container),
) -> ChatResponse:
    if not container.is_llm_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=container.llm_status.get("message") or "LLM model is still loading.",
        )

    if request.session_id is None:
        session = await container.sessions.create_session(
            user_id=request.user_id,
            unreal_client_id=request.unreal_client_id,
        )
    else:
        try:
            session = await container.sessions.require_session(request.session_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    message, command_id, command_status, events = await container.chat.handle_user_message(
        session_id=session.session_id,
        user_text=request.message,
        correlation_id=x_correlation_id,
        idempotency_key=request.idempotency_key,
    )
    return ChatResponse(
        session_id=session.session_id,
        correlation_id=message.correlation_id,
        message=message,
        command_id=command_id,
        status=command_status,
        events=events,
    )


@router.post("/events/robot-command", response_model=ChatResponse, tags=["events"])
async def receive_robot_event(
    request: CompletionEventRequest,
    container: AppContainer = Depends(get_container),
) -> ChatResponse:
    event = DomainEvent(
        event_type=request.event_type,
        correlation_id=request.correlation_id,
        session_id=request.session_id,
        command_id=request.command_id,
        payload=request.payload,
    )
    try:
        message = await container.chat.handle_completion_event(event)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ChatResponse(
        session_id=message.session_id,
        correlation_id=message.correlation_id,
        message=message,
        command_id=request.command_id,
        status=None,
        events=[event],
    )
