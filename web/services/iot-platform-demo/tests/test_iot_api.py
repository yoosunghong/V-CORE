from fastapi.testclient import TestClient

from app.main import create_app


def test_robot_command_generates_digital_twin_events() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/robots/commands",
        json={
            "command_id": "cmd_iot_harvest",
            "session_id": "session_iot",
            "command_name": "harvest_bed",
            "correlation_id": "corr_iot_harvest",
            "idempotency_key": "idem-iot-harvest",
            "parameters": {"bed_id": 2},
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "completed"

    events = client.get("/digital-twin/events").json()
    assert [event["event_type"] for event in events] == [
        "robot.command.accepted",
        "robot.moving",
        "robot.harvesting",
        "robot.command.completed",
    ]
    assert events[-1]["command_id"] == "cmd_iot_harvest"


def test_robot_command_is_idempotent() -> None:
    client = TestClient(create_app())
    payload = {
        "command_id": "cmd_iot_inspect",
        "session_id": "session_iot",
        "command_name": "inspect_bed",
        "correlation_id": "corr_iot_inspect",
        "idempotency_key": "idem-iot-inspect",
        "parameters": {"bed_id": 3},
    }

    first = client.post("/robots/commands", json=payload)
    second = client.post("/robots/commands", json={**payload, "command_id": "cmd_duplicate"})

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["command_id"] == second.json()["command_id"]


def test_sensor_and_actuator_mocks_are_queryable() -> None:
    client = TestClient(create_app())

    sensor_response = client.get("/sensors/snapshot")
    actuator_response = client.patch("/actuators/fan_zone_a", json={"status": "off"})

    assert sensor_response.status_code == 200
    assert sensor_response.json()["greenhouse_id"] == "greenhouse_demo"
    assert actuator_response.status_code == 200
    assert actuator_response.json()["status"] == "off"


def test_robot_command_failure_can_be_simulated() -> None:
    client = TestClient(create_app())
    client.post(
        "/robots/commands",
        json={
            "command_id": "cmd_iot_failure",
            "session_id": "session_iot",
            "command_name": "move_to_bed",
            "correlation_id": "corr_iot_failure",
            "idempotency_key": "idem-iot-failure",
            "parameters": {"bed_id": 4},
        },
    )

    response = client.post(
        "/robots/commands/cmd_iot_failure/simulate-failure",
        json={"reason": "path_blocked"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert client.get("/digital-twin/events").json()[-1]["event_type"] == "robot.command.failed"
