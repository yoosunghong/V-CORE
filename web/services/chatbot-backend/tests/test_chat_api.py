import asyncio

from fastapi.testclient import TestClient

from app.domain.models import ChatMessage, MessageRole
from app.main import create_app


def test_chat_message_issues_station_task_and_demo_completion() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/chat/messages",
        json={"message": "2번 스테이션에서 작업해줘", "user_id": "demo-user"},
        headers={"x-correlation-id": "corr_test_task"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["command_id"].startswith("cmd_")
    assert body["status"] == "completed"
    proposed = next(e for e in body["events"] if e["event_type"] == "llm.tool_call.proposed")
    assert proposed["payload"]["tool_name"] == "run_station_task"
    assert proposed["payload"]["arguments"]["station_id"] == 2


def test_sim_start_command_completes() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/chat/messages",
        json={"message": "시뮬레이션 시작해줘"},
        headers={"x-correlation-id": "corr_test_sim_start"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    proposed = next(e for e in body["events"] if e["event_type"] == "llm.tool_call.proposed")
    assert proposed["payload"]["tool_name"] == "start_simulation"


def test_chat_start_without_count_uses_cell_max() -> None:
    client = TestClient(create_app())

    start = client.post(
        "/chat/messages",
        json={"message": "시뮬레이션 시작해줘"},
        headers={"x-correlation-id": "corr_test_start_no_count"},
    )
    assert start.status_code == 200
    created = next(
        e for e in start.json()["events"] if e["event_type"] == "simulation.created"
    )
    simulation_id = created["payload"]["simulation_id"]

    simulations = client.get("/api/v1/simulations").json()["simulations"]
    chat_simulation = next(s for s in simulations if s["simulation_id"] == simulation_id)
    # No count specified → run the cell at capacity. Mock telemetry reports no max_agvs, so the
    # AGV_FLEET_MAX fallback (5) is used instead of the old hardcoded default of 3.
    assert chat_simulation["agv_count"] == 5


def test_chat_start_registers_simulation_and_stop_updates_run() -> None:
    client = TestClient(create_app())

    start = client.post(
        "/chat/messages",
        json={"message": "AGV 4대로 시뮬레이션 시작해줘"},
        headers={"x-correlation-id": "corr_test_chat_simulation"},
    )
    assert start.status_code == 200
    created = next(
        e for e in start.json()["events"] if e["event_type"] == "simulation.created"
    )
    assert created["payload"]["source"] == "chat"
    simulation_id = created["payload"]["simulation_id"]

    simulations = client.get("/api/v1/simulations").json()["simulations"]
    chat_simulation = next(s for s in simulations if s["simulation_id"] == simulation_id)
    assert chat_simulation["agv_count"] == 4

    runs = client.get(f"/api/v1/simulations/{simulation_id}/runs").json()["runs"]
    assert any(run["status"] == "running" for run in runs)

    stop = client.post(
        "/chat/messages",
        json={"message": "시뮬레이션 정지해줘"},
        headers={"x-correlation-id": "corr_test_chat_simulation_stop"},
    )
    assert stop.status_code == 200
    assert any(e["event_type"] == "simulation.run.updated" for e in stop.json()["events"])

    runs_after = client.get(f"/api/v1/simulations/{simulation_id}/runs").json()["runs"]
    assert runs_after and all(run["status"] == "stopped" for run in runs_after)


def test_abort_requires_confirmation_then_executes_stored_command() -> None:
    client = TestClient(create_app())

    start = client.post(
        "/chat/messages",
        json={"message": "Run simulation with 3 AGVs"},
        headers={"x-correlation-id": "corr_test_abort_start"},
    )
    assert start.status_code == 200
    session_id = start.json()["session_id"]
    created = next(e for e in start.json()["events"] if e["event_type"] == "simulation.created")
    simulation_id = created["payload"]["simulation_id"]

    abort = client.post(
        "/chat/messages",
        json={"session_id": session_id, "message": "abort"},
        headers={"x-correlation-id": "corr_test_abort_pending"},
    )
    assert abort.status_code == 200
    abort_body = abort.json()
    assert abort_body["status"] == "pending_confirmation"
    assert abort_body["command_id"] is None
    assert "confirm" in abort_body["message"]["content"].lower()

    still_running = client.get(f"/api/v1/simulations/{simulation_id}/runs").json()["runs"]
    assert any(run["status"] == "running" for run in still_running)

    confirmed = client.post(
        "/chat/messages",
        json={"session_id": session_id, "message": "confirm"},
        headers={"x-correlation-id": "corr_test_abort_confirm"},
    )
    assert confirmed.status_code == 200
    confirmed_body = confirmed.json()
    assert confirmed_body["command_id"] is not None
    proposed = next(e for e in confirmed_body["events"] if e["event_type"] == "llm.tool_call.proposed")
    assert proposed["payload"]["tool_name"] == "stop_simulation"

    runs_after = client.get(f"/api/v1/simulations/{simulation_id}/runs").json()["runs"]
    assert runs_after and all(run["status"] == "stopped" for run in runs_after)


def test_ue5_completion_updates_chat_started_simulation_run() -> None:
    client = TestClient(create_app())

    start = client.post(
        "/chat/messages",
        json={"message": "Run simulation with 4 AGVs"},
        headers={"x-correlation-id": "corr_test_chat_simulation_complete"},
    )
    assert start.status_code == 200
    body = start.json()
    session_id = body["session_id"]
    command_id = body["command_id"]
    created = next(
        e for e in body["events"] if e["event_type"] == "simulation.created"
    )
    simulation_id = created["payload"]["simulation_id"]
    run_id = created["payload"]["run_id"]

    with client.websocket_connect(f"/chat/sessions/{session_id}/events") as websocket:
        completion = client.post(
            "/internal/ue5/events",
            json={
                "session_id": session_id,
                "event_type": "robot.command.completed",
                "correlation_id": "corr_test_chat_simulation_complete",
                "command_id": command_id,
                "payload": {"kpis": {"throughput": 72.5, "avg_wait_time": 4.0}},
            },
            headers={"x-agv-api-key": "dev-agv-key"},
        )
        assert completion.status_code == 200
        run_update = None
        for _ in range(20):
            candidate = websocket.receive_json()
            if candidate["event_type"] == "simulation.run.updated":
                run_update = candidate
                break

    assert run_update is not None
    assert run_update["event_type"] == "simulation.run.updated"
    assert run_update["payload"]["simulation_id"] == simulation_id
    assert run_update["payload"]["run_id"] == run_id
    assert run_update["payload"]["status"] == "completed"

    runs_after = client.get(f"/api/v1/simulations/{simulation_id}/runs").json()["runs"]
    completed_run = next(run for run in runs_after if run["run_id"] == run_id)
    assert completed_run["status"] == "completed"
    assert completed_run["ended_at"] is not None
    assert completed_run["kpis_json"]["throughput"] == 72.5


def test_set_sim_speed_command_parses_multiplier() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/chat/messages",
        json={"message": "속도 1.5배로 설정해줘"},
        headers={"x-correlation-id": "corr_test_speed"},
    )

    assert response.status_code == 200
    body = response.json()
    proposed = next(e for e in body["events"] if e["event_type"] == "llm.tool_call.proposed")
    assert proposed["payload"]["tool_name"] == "set_sim_speed"
    assert proposed["payload"]["arguments"]["speed_multiplier"] == 1.5


def test_process_status_returns_telemetry_without_command() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/chat/messages",
        json={"message": "현재 공정 상태 알려줘"},
        headers={"x-correlation-id": "corr_test_status"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["command_id"] is None
    assert body["status"] is None
    assert "68.2" in body["message"]["content"]
    types = event_types(body)
    assert "process.telemetry.reported" in types
    assert types[-1] == "agent.turn.traced"


def test_session_delete_removes_session_and_history() -> None:
    client = TestClient(create_app())

    created = client.post(
        "/chat/messages",
        json={"message": "현재 공정 상태 알려줘", "user_id": "delete-user"},
        headers={"x-correlation-id": "corr_test_delete"},
    )
    assert created.status_code == 200
    session_id = created.json()["session_id"]

    listed = client.get("/chat/sessions", params={"user_id": "delete-user"})
    assert any(s["session_id"] == session_id for s in listed.json()["sessions"])

    deleted = client.delete(f"/chat/sessions/{session_id}")
    assert deleted.status_code == 204

    after = client.get("/chat/sessions", params={"user_id": "delete-user"})
    assert all(s["session_id"] != session_id for s in after.json()["sessions"])

    missing = client.get(f"/chat/sessions/{session_id}/messages")
    assert missing.status_code == 404

    assert client.delete(f"/chat/sessions/{session_id}").status_code == 404


def test_session_history_zero_limits_return_every_full_message() -> None:
    client = TestClient(create_app())
    first = client.post(
        "/chat/messages",
        json={"message": "현재 공정 상태 알려줘", "user_id": "history-user"},
        headers={"x-correlation-id": "corr_history_0"},
    )
    session_id = first.json()["session_id"]
    container = client.app.state.container

    long_content = "가" * 9000
    for index in range(45):
        asyncio.run(container.repository.add_message(ChatMessage(
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=long_content if index == 0 else f"history-{index}",
            correlation_id=f"corr_history_{index + 1}",
        )))

    response = client.get(
        f"/chat/sessions/{session_id}/messages",
        params={"limit": 0, "max_content_chars": 0},
    )
    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 47
    assert messages[2]["content"] == long_content


def test_simulation_crud_and_run_controls() -> None:
    client = TestClient(create_app())

    create_response = client.post(
        "/api/v1/simulations",
        json={
            "name": "10 AGV speed test",
            "agv_count": 10,
            "speed_multiplier": 1.5,
            "workload_percent": 120,
            "policy_id": "POLICY_FIFO",
            "duration_seconds": 300,
            "bottleneck_threshold_sec": 8,
        },
    )
    assert create_response.status_code == 201
    simulation = create_response.json()
    assert simulation["agv_count"] == 10

    run_response = client.post(f"/api/v1/simulations/{simulation['simulation_id']}/run")
    assert run_response.status_code == 200
    run = run_response.json()
    assert run["status"] == "running"
    assert run["speed_multiplier"] == 1.5

    speed_response = client.post(
        f"/api/v1/runs/{run['run_id']}/speed",
        json={"speed_multiplier": 4},
    )
    assert speed_response.status_code == 200
    assert speed_response.json()["speed_multiplier"] == 4

    pause_response = client.post(f"/api/v1/runs/{run['run_id']}/pause")
    assert pause_response.status_code == 200
    assert pause_response.json()["status"] == "paused"

    resume_response = client.post(f"/api/v1/runs/{run['run_id']}/resume")
    assert resume_response.status_code == 200
    assert resume_response.json()["status"] == "running"

    stop_response = client.post(f"/api/v1/runs/{run['run_id']}/stop")
    assert stop_response.status_code == 200
    stopped = stop_response.json()
    assert stopped["status"] == "stopped"
    assert stopped["kpis_json"]["throughput"] == 68.2

    result_response = client.get(f"/api/v1/runs/{run['run_id']}/result")
    assert result_response.status_code == 200
    assert result_response.json()["run"]["kpis_json"]["active_agvs"] == 3


def test_dashboard_overlay_returns_virtual_process_panels() -> None:
    client = TestClient(create_app())

    response = client.get("/dashboard/overlay")

    assert response.status_code == 200
    body = response.json()
    assert body["cell_id"] == "VP-CELL-048-ALPHA"
    assert [zone["name"] for zone in body["zones"]] == ["ZONE 1", "ZONE 2", "ZONE 3"]
    assert any(metric["id"] == "throughput" for metric in body["metrics"])


def test_unreal_viewport_returns_stream_and_sse_contract(monkeypatch) -> None:
    monkeypatch.setenv("UE5_CLIENT_MODE", "ue5")
    monkeypatch.setenv("UE5_VIEW_URL", "http://localhost:8880")
    client = TestClient(create_app())

    response = client.get("/unreal/viewport")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "ue5"
    assert body["stream_url"] == "http://localhost:8880"
    assert body["telemetry_sse_url"] == "/unreal/telemetry/stream"


def test_unreal_telemetry_stream_emits_sse_event() -> None:
    client = TestClient(create_app())

    with client.stream("GET", "/unreal/telemetry/stream?once=true") as response:
        first_chunk = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: telemetry" in first_chunk
    assert "data: " in first_chunk


def test_ue5_internal_stream_ingests_live_telemetry(monkeypatch) -> None:
    from app.interfaces import ue5_ingest

    async def skip_collector_forward(container, node) -> None:
        return None

    monkeypatch.setattr(ue5_ingest, "_forward_telemetry", skip_collector_forward)
    client = TestClient(create_app())

    with client.websocket_connect(
        "/internal/ue5/stream",
        headers={"x-agv-api-key": "dev-agv-key"},
    ) as websocket:
        websocket.send_json(
            {
                "kind": "agv",
                "cell_id": "cell_demo",
                "agv_id": "AGV-01",
                "state": "moving",
                "speed": 1.2,
            }
        )
        websocket.send_json(
            {
                "kind": "process",
                "cell_id": "cell_demo",
                "running": True,
                "active_agvs": 1,
                "throughput": 12.5,
                "progress_percent": 25.0,
                "policy_id": "POLICY_FIFO",
            }
        )

    with client.stream("GET", "/unreal/telemetry/stream?once=true") as response:
        first_chunk = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: agvs" in first_chunk
    assert '"agv_id": "AGV-01"' in first_chunk
    assert "event: process" in first_chunk
    assert '"active_agvs": 1' in first_chunk
    assert "event: hud" in first_chunk
    assert '"progress_percent": 25.0' in first_chunk


def test_ue5_events_fan_out_to_multiple_frontend_websockets() -> None:
    client = TestClient(create_app())
    created = client.post("/chat/sessions", json={"user_id": "fanout-user"})
    assert created.status_code == 201
    session_id = created.json()["session_id"]

    with client.websocket_connect(f"/chat/sessions/{session_id}/events") as first:
        with client.websocket_connect(f"/chat/sessions/{session_id}/events") as second:
            event = {
                "session_id": session_id,
                "event_type": "robot.moving",
                "correlation_id": "corr_fanout",
                "command_id": "cmd_fanout",
                "payload": {"agv_id": "AGV-01", "state": "moving"},
            }
            response = client.post(
                "/internal/ue5/events",
                json=event,
                headers={"x-agv-api-key": "dev-agv-key"},
            )

            assert response.status_code == 200
            first_event = first.receive_json()
            second_event = second.receive_json()

    assert first_event["event_type"] == "robot.moving"
    assert first_event["payload"]["agv_id"] == "AGV-01"
    assert second_event["event_type"] == "robot.moving"
    assert second_event["payload"]["agv_id"] == "AGV-01"


def test_web_frontend_origin_is_allowed_by_cors() -> None:
    client = TestClient(create_app())

    response = client.options(
        "/chat/messages",
        headers={"origin": "http://localhost:5180", "access-control-request-method": "POST"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5180"


def event_types(body: dict) -> list[str]:
    return [event["event_type"] for event in body["events"]]
