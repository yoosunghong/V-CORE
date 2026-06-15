from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
SEED_DIR = BASE_DIR / "seeds"


def load_json(name: str) -> list[dict[str, Any]]:
    with (SEED_DIR / name).open(encoding="utf-8") as file:
        return json.load(file)


def build_sensor_readings() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = now - timedelta(hours=24)
    readings: list[dict[str, Any]] = []
    metrics = [
        ("sensor_temp_01", "temperature_celsius", "celsius", 22.4),
        ("sensor_humidity_01", "humidity_percent", "percent", 61.0),
        ("sensor_co2_01", "co2_ppm", "ppm", 790.0),
        ("sensor_light_01", "illuminance_lux", "lux", 17800.0),
    ]
    steps = int(timedelta(hours=24) / timedelta(minutes=5)) + 1
    for index in range(steps):
        measured_at = start + timedelta(minutes=5 * index)
        for sensor_id, metric, unit, base_value in metrics:
            variation = (index % 12) * 0.3
            readings.append(
                {
                    "greenhouse_id": "greenhouse_demo",
                    "sensor_id": sensor_id,
                    "metric": metric,
                    "value": round(base_value + variation, 2),
                    "unit": unit,
                    "measured_at": measured_at.isoformat(),
                }
            )
    return readings


def build_robot_history() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    return [
        {
            "robot_id": "robot_demo_1",
            "status": "idle",
            "bed_id": 1,
            "battery_percent": 87,
            "recorded_at": (now - timedelta(minutes=15)).isoformat(),
        },
        {
            "robot_id": "robot_demo_1",
            "status": "moving",
            "bed_id": 2,
            "battery_percent": 86,
            "recorded_at": (now - timedelta(minutes=10)).isoformat(),
        },
        {
            "robot_id": "robot_demo_1",
            "status": "idle",
            "bed_id": 2,
            "battery_percent": 86,
            "recorded_at": now.isoformat(),
        },
    ]


def main() -> None:
    payload = {
        "greenhouses": load_json("greenhouses.json"),
        "beds": load_json("beds.json"),
        "robots": load_json("robots.json"),
        "actuators": load_json("actuators.json"),
        "sensor_readings": build_sensor_readings(),
        "robot_state_history": build_robot_history(),
        "rag_documents_path": str(SEED_DIR / "rag_documents.jsonl"),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
