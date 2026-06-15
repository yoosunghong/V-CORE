import asyncio

import httpx

from app.domain.models import Station
from app.infrastructure.control_client import HttpControlServerClient


def test_http_control_client_maps_station_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/stations/2"
        assert request.headers["x-correlation-id"] == "corr_http_control"
        return httpx.Response(
            200,
            json={
                "station_id": 2,
                "station_type": "work",
                "task_ready": True,
                "cell_id": "cell_demo",
                "zone": "A",
                "state": "task_ready",
                "accessible": True,
            },
        )

    async def run() -> Station:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://control.test") as client:
            control_client = HttpControlServerClient(
                base_url="http://control.test",
                client=client,
            )
            return await control_client.get_station(2, "corr_http_control")

    station = asyncio.run(run())

    assert station == Station(
        station_id=2,
        station_type="work",
        task_ready=True,
        cell_id="cell_demo",
        zone="A",
        state="task_ready",
        accessible=True,
    )


def test_http_control_client_lists_stations_from_cell_status() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/cell/status"
        return httpx.Response(
            200,
            json={
                "cell_id": "cell_demo",
                "stations": [
                    {"station_id": 1, "station_type": "loading", "task_ready": False, "state": "idle"},
                    {"station_id": 2, "station_type": "work", "task_ready": True, "state": "task_ready"},
                ],
            },
        )

    async def run() -> list[Station]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="http://control.test") as client:
            control_client = HttpControlServerClient(base_url="http://control.test", client=client)
            return await control_client.list_stations("corr_cell")

    stations = asyncio.run(run())
    assert [station.station_id for station in stations] == [1, 2]
