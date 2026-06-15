from fastapi.testclient import TestClient

from app.main import create_app


def test_cell_status_exposes_demo_stations_and_telemetry() -> None:
    client = TestClient(create_app())

    response = client.get("/cell/status")

    assert response.status_code == 200
    body = response.json()
    assert body["cell_id"] == "cell_demo"
    assert {station["station_id"] for station in body["stations"]} >= {1, 2, 3, 4}
    assert body["telemetry"]["active_agvs"] == 3


def test_get_station_returns_task_readiness_for_chatbot_context() -> None:
    client = TestClient(create_app())

    response = client.get("/stations/2", headers={"x-correlation-id": "corr_control_station"})

    assert response.status_code == 200
    body = response.json()
    assert body["station_id"] == 2
    assert body["station_type"] == "work"
    assert body["task_ready"] is True


def test_create_task_is_idempotent_and_queryable() -> None:
    client = TestClient(create_app())
    payload = {
        "command_name": "run_station_task",
        "target_type": "station",
        "target_id": "2",
        "correlation_id": "corr_control_task",
        "idempotency_key": "idem-control-task-1",
        "parameters": {"station_id": 2},
    }

    first = client.post("/tasks", json=payload)
    second = client.post("/tasks", json=payload)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["task_id"] == second.json()["task_id"]

    task_response = client.get(f"/tasks/{first.json()['task_id']}")
    assert task_response.status_code == 200
    assert task_response.json()["status"] == "accepted"


def test_publish_event_records_event_and_updates_task_status() -> None:
    client = TestClient(create_app())
    task = client.post(
        "/tasks",
        json={
            "command_name": "inspect_station",
            "target_type": "station",
            "target_id": "3",
            "correlation_id": "corr_control_event",
            "idempotency_key": "idem-control-event-1",
            "parameters": {"station_id": 3},
        },
    ).json()

    response = client.post(
        "/events",
        json={
            "event_type": "control.task.completed",
            "correlation_id": "corr_control_event",
            "task_id": task["task_id"],
            "payload": {"operator": "demo"},
        },
    )

    assert response.status_code == 202
    assert response.json()["event_type"] == "control.task.completed"
    assert client.get(f"/tasks/{task['task_id']}").json()["status"] == "completed"
    assert client.get("/events").json()[0]["task_id"] == task["task_id"]
