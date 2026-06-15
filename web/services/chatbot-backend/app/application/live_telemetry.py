from __future__ import annotations

import time
from typing import Any

# Frames older than this (seconds) are treated as stale: when a simulation stops, UE5
# stops emitting telemetry entirely (no "running: false" frame is sent), so the live
# feed must report an empty cell rather than a frozen one.
_STALE_AFTER_SECONDS = 5.0

# HUD fields carried on the process frame (see AGVSimController::EmitTelemetry). Extracted
# here so the web overlay can render the in-process HUD that used to be baked into UE5.
_HUD_FIELDS = (
    ("running", False),
    ("paused", False),
    ("speed_multiplier", 1.0),
    ("progress_percent", 0.0),
    ("progress_basis", "real_time"),
    ("sim_elapsed_seconds", 0.0),
    ("sim_target_duration_seconds", 0.0),
    ("tasks_completed", 0),
    ("collisions", 0),
    ("policy_id", ""),
    ("recent_events", []),
    ("verdict_summary", ""),
    ("verdict_passed", True),
)


class LiveTelemetryHub:
    """In-memory cache of the latest AGV / process / HUD frames streamed from UE5 over the
    backend WebSocket (interfaces/ue5_ingest.py).

    Served to the web overlay via the /unreal/telemetry/stream SSE so the live view does not
    depend on the Firebase delivery path, which does not traverse the Windows Docker proxy
    reliably. Firebase remains an optional secondary path for the dashboard.
    """

    def __init__(self) -> None:
        self._agvs: dict[str, dict[str, Any]] = {}
        self._process: dict[str, Any] | None = None
        self._updated_at: float = 0.0

    def ingest(self, frame: dict[str, Any]) -> None:
        kind = frame.get("kind") or ("agv" if frame.get("agv_id") else "process")
        if kind == "agv":
            agv_id = frame.get("agv_id")
            if not agv_id:
                return
            self._agvs[str(agv_id)] = frame
        else:
            self._process = frame
        self._updated_at = time.monotonic()

    def _is_stale(self) -> bool:
        return self._updated_at == 0.0 or (time.monotonic() - self._updated_at) > _STALE_AFTER_SECONDS

    def has_live_data(self) -> bool:
        return not self._is_stale() and self._process is not None

    def agvs(self) -> list[dict[str, Any]]:
        if self._is_stale():
            return []
        return sorted(self._agvs.values(), key=lambda agv: str(agv.get("agv_id", "")))

    def process(self) -> dict[str, Any] | None:
        if self._is_stale():
            return None
        return self._process

    def hud(self) -> dict[str, Any] | None:
        process = self.process()
        if process is None:
            return None
        return {key: process.get(key, default) for key, default in _HUD_FIELDS}
