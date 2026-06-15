from __future__ import annotations

from app.agents.failure_policy import LlmGatewayError
from app.agents.planning_fallback import RuleBasedPlanningFallback
from app.application.ports import LlmGateway


class PlanningAgent:
    """Builds user-visible orchestration plans for chat requests."""

    def __init__(self) -> None:
        self._fallback = RuleBasedPlanningFallback()

    async def build_steps(
        self,
        user_message: str,
        correlation_id: str,
        llm: LlmGateway,
    ) -> tuple[list[str], str]:
        try:
            return await llm.generate_plan_steps(user_message, correlation_id), "llm"
        except LlmGatewayError:
            return self._fallback.build_steps(user_message), "fallback"
