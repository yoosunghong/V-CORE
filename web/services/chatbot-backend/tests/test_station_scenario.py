from fastapi.testclient import TestClient

from app.main import create_app as create_chatbot_app


def test_station_task_completion_event_generates_report(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_COMPLETE_DEMO_COMMANDS", "false")
    chatbot = TestClient(create_chatbot_app())

    chat_response = chatbot.post(
        "/chat/messages",
        json={
            "message": "2번 스테이션에서 작업해줘",
            "user_id": "demo-user",
            "unreal_client_id": "ue-client-01",
            "idempotency_key": "ue-chat-e2e-001",
        },
        headers={"x-correlation-id": "corr_e2e_task"},
    )

    assert chat_response.status_code == 200
    chat_body = chat_response.json()
    assert chat_body["status"] == "accepted"
    assert chat_body["command_id"].startswith("cmd_")

    report_response = chatbot.post(
        "/events/robot-command",
        json={
            "event_type": "robot.command.completed",
            "correlation_id": chat_body["correlation_id"],
            "session_id": chat_body["session_id"],
            "command_id": chat_body["command_id"],
            "payload": {"robot_id": "agv_demo_1", "station_id": 2},
        },
    )

    assert report_response.status_code == 200
    assert "Station 2 task is complete." in report_response.json()["message"]["content"]


def test_station_task_failure_event_generates_report(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_COMPLETE_DEMO_COMMANDS", "false")
    chatbot = TestClient(create_chatbot_app())

    chat_body = chatbot.post(
        "/chat/messages",
        json={"message": "2번 스테이션에서 작업해줘", "idempotency_key": "ue-chat-e2e-002"},
        headers={"x-correlation-id": "corr_e2e_failure"},
    ).json()

    report_response = chatbot.post(
        "/events/robot-command",
        json={
            "event_type": "robot.command.failed",
            "correlation_id": chat_body["correlation_id"],
            "session_id": chat_body["session_id"],
            "command_id": chat_body["command_id"],
            "payload": {"robot_id": "agv_demo_1", "station_id": 2, "reason": "path_blocked"},
        },
    )

    assert report_response.status_code == 200
    assert "path_blocked" in report_response.json()["message"]["content"]
