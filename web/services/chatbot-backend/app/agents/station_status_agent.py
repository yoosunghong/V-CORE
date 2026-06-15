from __future__ import annotations

import re

from app.application.ports import ControlServerClient
from app.domain.models import Station


class StationStatusAgent:
    def __init__(self, control_client: ControlServerClient) -> None:
        self._control_client = control_client

    async def resolve_station(self, user_message: str, correlation_id: str) -> Station | None:
        station_id = self._extract_station_id(user_message)
        if station_id is None:
            return None
        return await self._control_client.get_station(station_id, correlation_id)

    async def list_stations(self, correlation_id: str) -> list[Station]:
        return await self._control_client.list_stations(correlation_id)

    def _extract_station_id(self, text: str) -> int | None:
        patterns = (
            r"(?:station|스테이션|설비)\s*#?\s*(\d+)",
            r"(\d+)\s*(?:번)?\s*(?:station|스테이션|설비)",
            r"(\d+)\s*번\s*(?:스테이션|구역|라인)?",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None
