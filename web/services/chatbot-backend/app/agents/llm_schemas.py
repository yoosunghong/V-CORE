from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.domain.models import RobotCommandName, ToolCall


class IntentDecision(BaseModel):
    intent: Literal["process_status", "station_action_query", "robot_command"]


class PlanDecision(BaseModel):
    steps: list[str] = Field(min_length=2, max_length=5)

    @field_validator("steps")
    @classmethod
    def _clean_steps(cls, value: list[str]) -> list[str]:
        cleaned = [str(step).strip() for step in value if str(step).strip()]
        if not 2 <= len(cleaned) <= 5:
            raise ValueError("plan must include 2 to 5 non-empty steps")
        return cleaned


class ToolCallDecision(BaseModel):
    name: RobotCommandName
    arguments: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_llm_payload(cls, payload: dict[str, Any]) -> ToolCall:
        try:
            decision = cls.model_validate(
                {
                    "name": payload.get("name") or payload.get("tool_name") or payload.get("tool"),
                    "arguments": payload.get("arguments") or payload.get("parameters") or {},
                }
            )
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        return ToolCall(name=decision.name, arguments=decision.arguments)
