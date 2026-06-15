from __future__ import annotations

import httpx
from pydantic import ValidationError

from app.domain.models import Station


class DemoControlServerClient:
    _stations = {
        1: Station(
            station_id=1,
            station_type="loading",
            task_ready=False,
            cell_id="cell_demo",
            zone="A",
            state="idle",
        ),
        2: Station(
            station_id=2,
            station_type="work",
            task_ready=True,
            cell_id="cell_demo",
            zone="A",
            state="task_ready",
        ),
        3: Station(
            station_id=3,
            station_type="inspection",
            task_ready=False,
            cell_id="cell_demo",
            zone="B",
            state="idle",
        ),
        4: Station(
            station_id=4,
            station_type="unloading",
            task_ready=True,
            cell_id="cell_demo",
            zone="B",
            state="task_ready",
            accessible=False,
        ),
    }

    async def get_station(self, station_id: int, correlation_id: str) -> Station:
        try:
            return self._stations[station_id]
        except KeyError as exc:
            raise ValueError(f"Unknown station_id: {station_id}") from exc

    async def list_stations(self, correlation_id: str) -> list[Station]:
        return list(self._stations.values())


class HttpControlServerClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 5.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def get_station(self, station_id: int, correlation_id: str) -> Station:
        headers = {"x-correlation-id": correlation_id}
        if self._client is not None:
            response = await self._client.get(f"/stations/{station_id}", headers=headers)
        else:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.get(f"/stations/{station_id}", headers=headers)

        response.raise_for_status()
        try:
            return Station.model_validate(response.json())
        except ValidationError as exc:
            raise ValueError("Control server returned an invalid station payload") from exc

    async def list_stations(self, correlation_id: str) -> list[Station]:
        headers = {"x-correlation-id": correlation_id}
        if self._client is not None:
            response = await self._client.get("/cell/status", headers=headers)
        else:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.get("/cell/status", headers=headers)

        response.raise_for_status()
        payload = response.json()
        try:
            return [Station.model_validate(item) for item in payload.get("stations", [])]
        except ValidationError as exc:
            raise ValueError("Control server returned an invalid cell status payload") from exc
