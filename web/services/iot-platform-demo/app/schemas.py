from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain import RobotCommandName


class RobotCommandRequest(BaseModel):
    command_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    command_name: RobotCommandName
    correlation_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class SetActuatorStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=40)


class SimulateFailureRequest(BaseModel):
    reason: str = Field(default="demo_failure", min_length=1, max_length=200)
