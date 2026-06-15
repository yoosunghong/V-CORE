from __future__ import annotations

from app.application.ports import LlmGateway
from app.domain.models import Station
from app.tools.contracts import ValidatedToolCall
from app.tools.router import ToolRouter


class RobotControlAgent:
    def __init__(self, llm: LlmGateway, tool_router: ToolRouter) -> None:
        self._llm = llm
        self._tool_router = tool_router

    async def plan_tool_call(
        self,
        user_message: str,
        station: Station | None,
        correlation_id: str,
    ) -> ValidatedToolCall | None:
        tool_call = await self._llm.propose_tool_call(user_message, station, correlation_id)
        if tool_call is None:
            return None
        return self._tool_router.validate(tool_call)
