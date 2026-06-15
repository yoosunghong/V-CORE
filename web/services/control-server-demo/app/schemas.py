from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain import TaskStatus


class CreateTaskRequest(BaseModel):
    command_name: str = Field(min_length=1, max_length=80)
    target_type: str = Field(min_length=1, max_length=40)
    target_id: str = Field(min_length=1, max_length=80)
    correlation_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class UpdateTaskStatusRequest(BaseModel):
    status: TaskStatus


class PublishEventRequest(BaseModel):
    event_type: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    task_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
