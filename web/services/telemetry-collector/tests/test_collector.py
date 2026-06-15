from __future__ import annotations

import json
import logging

from app.collector import TelemetryCollector
from app.main import _log_level_from_env


class FakeSink:
    def __init__(self) -> None:
        self.writes: list[tuple[str, dict]] = []

    def write(self, path: str, data: dict) -> None:
        self.writes.append((path, data))


def test_agv_datagram_writes_per_agv_path():
    sink = FakeSink()
    collector = TelemetryCollector(sink)
    raw = json.dumps(
        {
            "kind": "agv",
            "cell_id": "cell_demo",
            "agv_id": "AGV-1",
            "battery": 87.5,
            "speed": 2.2,
            "state": "MOVING_TO_PICKUP",
            "destination": "Pickup Dock",
        }
    )

    assert collector.handle_raw(raw) is True
    assert sink.writes == [("cells/cell_demo/agvs/AGV-1", json.loads(raw))]
    assert collector.latest_agvs["AGV-1"]["battery"] == 87.5


def test_process_datagram_writes_process_path():
    sink = FakeSink()
    collector = TelemetryCollector(sink)
    payload = {"kind": "process", "cell_id": "cell_demo", "throughput": 68.2, "progress_percent": 40.0}

    assert collector.handle_payload(payload) is True
    assert sink.writes[0][0] == "cells/cell_demo/process"
    assert collector.latest_process["throughput"] == 68.2


def test_kind_inferred_from_agv_id():
    sink = FakeSink()
    collector = TelemetryCollector(sink)
    assert collector.handle_payload({"agv_id": "AGV-2", "cell_id": "cell_demo"}) is True
    assert sink.writes[0][0] == "cells/cell_demo/agvs/AGV-2"


def test_invalid_payloads_are_dropped():
    sink = FakeSink()
    collector = TelemetryCollector(sink)
    assert collector.handle_raw("not json") is False
    assert collector.handle_raw("") is False
    assert collector.handle_payload({"kind": "agv", "cell_id": "c"}) is False  # no agv_id
    assert sink.writes == []


def test_firebase_key_sanitizes_forbidden_chars():
    sink = FakeSink()
    collector = TelemetryCollector(sink)
    collector.handle_payload({"agv_id": "AGV.1/x", "cell_id": "cell.demo"})
    assert sink.writes[0][0] == "cells/cell_demo/agvs/AGV_1_x"


def test_log_level_accepts_lowercase_env(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "info")
    assert _log_level_from_env() == "INFO"


def test_log_level_falls_back_for_unknown_env(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "chatty")
    assert _log_level_from_env() == logging.INFO
