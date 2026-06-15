from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.collector import TelemetryCollector
from app.firebase_writer import build_sink


def _log_level_from_env() -> str | int:
    level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    return level if level in logging.getLevelNamesMapping() else logging.INFO


logging.basicConfig(level=_log_level_from_env())
logger = logging.getLogger(__name__)

UDP_PORT = int(os.getenv("TELEMETRY_UDP_PORT", "9999"))
TCP_PORT = int(os.getenv("TELEMETRY_TCP_PORT", "9998"))
FIREBASE_ROOT = os.getenv("FIREBASE_CELL_ROOT", "cells")


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, collector: TelemetryCollector) -> None:
        self._collector = collector
        self._loop = asyncio.get_event_loop()

    def datagram_received(self, data: bytes, addr) -> None:  # noqa: ANN001
        # Firebase writes block; offload so the event loop keeps reading datagrams.
        self._loop.run_in_executor(None, self._collector.handle_raw, data)


async def _handle_tcp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, collector: TelemetryCollector) -> None:
    loop = asyncio.get_event_loop()
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            await loop.run_in_executor(None, collector.handle_raw, line)
    except (ConnectionResetError, asyncio.IncompleteReadError):
        pass
    finally:
        writer.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    collector = TelemetryCollector(build_sink(), root=FIREBASE_ROOT)
    app.state.collector = collector
    loop = asyncio.get_event_loop()

    udp_transport, _ = await loop.create_datagram_endpoint(
        lambda: _UdpProtocol(collector),
        local_addr=("0.0.0.0", UDP_PORT),
    )
    tcp_server = await asyncio.start_server(
        lambda r, w: _handle_tcp(r, w, collector), "0.0.0.0", TCP_PORT
    )
    logger.info("telemetry-collector listening: UDP :%d, TCP :%d", UDP_PORT, TCP_PORT)
    try:
        yield
    finally:
        udp_transport.close()
        tcp_server.close()
        await tcp_server.wait_closed()


app = FastAPI(title="telemetry-collector", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "telemetry-collector"}


@app.get("/debug/latest")
async def latest() -> dict:
    collector: TelemetryCollector = app.state.collector
    return {"agvs": collector.latest_agvs, "process": collector.latest_process}


@app.post("/ingest")
async def ingest(node: dict) -> dict:
    """HTTP ingest for telemetry forwarded by the backend (UE5 WebSocket path).

    UE5 raw-socket UDP/TCP to this service does not traverse Docker Desktop's
    Windows proxy reliably, so UE5 streams telemetry over its backend WebSocket and
    the backend forwards each node here over the in-Docker network.

    handle_payload performs a blocking firebase-admin write, so it runs in the
    default executor (as the UDP/TCP listeners do) to keep the event loop free and
    let concurrent writes overlap — otherwise the ~20 frames/s stream backs up.
    """
    collector: TelemetryCollector = app.state.collector
    loop = asyncio.get_event_loop()
    accepted = await loop.run_in_executor(None, collector.handle_payload, node)
    return {"accepted": accepted}
