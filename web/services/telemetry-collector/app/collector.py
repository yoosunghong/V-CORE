from __future__ import annotations

import json
import logging
from typing import Any

from app.firebase_writer import TelemetrySink

logger = logging.getLogger(__name__)


def _firebase_key(value: str) -> str:
    """Firebase RTDB keys cannot contain . $ # [ ] / — sanitize ids for path use."""
    return "".join("_" if ch in ".$#[]/" else ch for ch in value)


class TelemetryCollector:
    """Parses AGV/process telemetry datagrams and fans them out to a Firebase sink.

    Datagram contract (one JSON object per UDP packet or per TCP line):
      kind="agv":     { cell_id, agv_id, battery, speed, state, destination,
                        carrying_load, completed_tasks, position, ts }
      kind="process": { cell_id, running, paused, throughput, active_agvs,
                        avg_wait_time, collision_risk, uptime, progress_percent, ts }
    Messages without `kind` are inferred from the presence of `agv_id`.
    """

    def __init__(self, sink: TelemetrySink, root: str = "cells") -> None:
        self._sink = sink
        self._root = root.strip("/")
        # Last-known node per AGV + the latest process snapshot, for /debug/latest.
        self.latest_agvs: dict[str, dict[str, Any]] = {}
        self.latest_process: dict[str, Any] | None = None

    def handle_raw(self, raw: bytes | str) -> bool:
        """Decode + route one datagram. Returns True if it was a valid telemetry node."""
        text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
        text = text.strip()
        if not text:
            return False
        try:
            payload = json.loads(text)
        except ValueError:
            logger.debug("Dropping non-JSON datagram: %.80s", text)
            return False
        if not isinstance(payload, dict):
            return False
        return self.handle_payload(payload)

    def handle_payload(self, payload: dict[str, Any]) -> bool:
        cell_id = str(payload.get("cell_id") or "cell_demo")
        kind = payload.get("kind") or ("agv" if payload.get("agv_id") else "process")
        cell_key = _firebase_key(cell_id)

        if kind == "agv":
            agv_id = payload.get("agv_id")
            if not agv_id:
                return False
            agv_key = _firebase_key(str(agv_id))
            self.latest_agvs[str(agv_id)] = payload
            self._write(f"{self._root}/{cell_key}/agvs/{agv_key}", payload)
            return True

        self.latest_process = payload
        self._write(f"{self._root}/{cell_key}/process", payload)
        return True

    def _write(self, path: str, data: dict[str, Any]) -> None:
        try:
            self._sink.write(path, data)
        except Exception as exc:  # noqa: BLE001 - never let a sink error kill the listener
            logger.error("Sink write failed for %s: %s", path, exc)
