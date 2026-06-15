from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.domain.models import RobotCommandName


class ToolContract(BaseModel):
    name: RobotCommandName
    description: str
    required: list[str]
    properties: dict[str, Any]

    def to_json_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": self.required,
            "properties": self.properties,
            "additionalProperties": False,
        }

    def to_ollama_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name.value,
                "description": self.description,
                "parameters": self.to_json_schema(),
            },
        }


_STATION_ID_PROP = {"type": "integer", "description": "Target station number"}
_SPEED_PROP = {
    "type": "number",
    "description": "Simulation speed multiplier relative to baseline (1.0 = baseline)",
}

# F4 — optional acceptance criteria the agent attaches to a run. The UE5 engine evaluates
# each against the final KPIs and returns a PASS/FAIL verdict the agent reports back in chat.
_ACCEPTANCE_PROP = {
    "type": "array",
    "description": (
        "Optional pass/fail acceptance criteria for the run. Each item asserts one KPI against a "
        "threshold; the simulation returns a verdict (PASS only if every criterion passes). Use when "
        "the user frames a verifiable goal, e.g. 'throughput must stay above 70/h with zero collisions'."
    ),
    "items": {
        "type": "object",
        "required": ["metric", "comparator", "threshold"],
        "properties": {
            "label": {
                "type": "string",
                "description": "Human-readable criterion, e.g. 'throughput >= 70/h'",
            },
            "metric": {
                "type": "string",
                "enum": [
                    "throughput",
                    "avg_wait_sec",
                    "collision_count",
                    "uptime_ratio",
                    "active_agvs",
                    "bottleneck_rate",
                ],
                "description": "KPI to assert on",
            },
            "comparator": {
                "type": "string",
                "enum": [">=", "<=", "=="],
                "description": "Comparison applied between the measured KPI and threshold",
            },
            "threshold": {"type": "number", "description": "Threshold value the metric is compared against"},
        },
        "additionalProperties": False,
    },
}

ROBOT_TOOL_CONTRACTS: dict[RobotCommandName, ToolContract] = {
    RobotCommandName.RUN_STATION_TASK: ToolContract(
        name=RobotCommandName.RUN_STATION_TASK,
        description="Run the process task at the requested Virtual Process station.",
        required=["station_id"],
        properties={
            "station_id": _STATION_ID_PROP,
            "priority": {
                "type": "string",
                "enum": ["normal", "high"],
                "default": "normal",
                "description": "AGV command priority",
            },
        },
    ),
    RobotCommandName.MOVE_TO_STATION: ToolContract(
        name=RobotCommandName.MOVE_TO_STATION,
        description="Move the AGV to the requested Virtual Process station.",
        required=["station_id"],
        properties={"station_id": _STATION_ID_PROP},
    ),
    RobotCommandName.INSPECT_STATION: ToolContract(
        name=RobotCommandName.INSPECT_STATION,
        description="Inspect the requested Virtual Process station.",
        required=["station_id"],
        properties={"station_id": _STATION_ID_PROP},
    ),
    RobotCommandName.CANCEL_COMMAND: ToolContract(
        name=RobotCommandName.CANCEL_COMMAND,
        description="Cancel an existing AGV command.",
        required=["command_id"],
        properties={
            "command_id": {"type": "string", "description": "AGV command id to cancel"}
        },
    ),
    RobotCommandName.START_SIMULATION: ToolContract(
        name=RobotCommandName.START_SIMULATION,
        description="Start the Virtual Process simulation run in the UE5 cell.",
        required=[],
        properties={
            "agv_count": {
                "type": "integer",
                "default": 3,
                "description": "Number of AGVs to deploy",
            },
            "speed_multiplier": {**_SPEED_PROP, "default": 1.0},
            "simulation_name": {
                "type": "string",
                "description": "Display name for this simulation",
            },
            "acceptance": _ACCEPTANCE_PROP,
        },
    ),
    RobotCommandName.STOP_SIMULATION: ToolContract(
        name=RobotCommandName.STOP_SIMULATION,
        description="Stop the running Virtual Process simulation.",
        required=[],
        properties={},
    ),
    RobotCommandName.PAUSE_SIMULATION: ToolContract(
        name=RobotCommandName.PAUSE_SIMULATION,
        description="Pause the running Virtual Process simulation.",
        required=[],
        properties={},
    ),
    RobotCommandName.RESUME_SIMULATION: ToolContract(
        name=RobotCommandName.RESUME_SIMULATION,
        description="Resume the paused Virtual Process simulation.",
        required=[],
        properties={},
    ),
    RobotCommandName.SET_SIM_SPEED: ToolContract(
        name=RobotCommandName.SET_SIM_SPEED,
        description="Set the Virtual Process simulation speed multiplier.",
        required=["speed_multiplier"],
        properties={"speed_multiplier": _SPEED_PROP},
    ),
}


class ToolValidationError(ValueError):
    pass


class ValidatedToolCall(BaseModel):
    name: RobotCommandName
    arguments: dict[str, Any] = Field(default_factory=dict)
