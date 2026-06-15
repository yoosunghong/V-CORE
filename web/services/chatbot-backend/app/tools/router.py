from __future__ import annotations

from typing import Any

from app.domain.models import RobotCommandName, ToolCall
from app.tools.contracts import ROBOT_TOOL_CONTRACTS, ToolValidationError, ValidatedToolCall

# Tools the agent may still use internally (as a plan sub-step) but that the user must not be
# able to trigger by an explicit request. move_to_station stays a valid contract for internal
# use; it is simply withheld from the tool list offered to the LLM when planning a *user* turn.
_INTERNAL_ONLY_TOOLS = frozenset({RobotCommandName.MOVE_TO_STATION})

_ACCEPTANCE_METRICS = {
    "throughput",
    "avg_wait_sec",
    "collision_count",
    "uptime_ratio",
    "active_agvs",
    "bottleneck_rate",
}
_ACCEPTANCE_COMPARATORS = {">=", "<=", "=="}

# Phase-2-B Fix #2 — semantic value-range bounds for tool arguments. The Phase-2-A
# validator only type-checked, so station -1 / station 999 / speed 0 / speed -2x all
# dispatched straight to UE5. These bounds reject physically meaningless values so the
# layer can repair or decline instead of silently acting. Ranges are inclusive and sized
# to admit every gold-labelled positive case in the v2 suite (station ≤ 12, speed 0.5–3,
# agv 3–8) while rejecting the invalid_parameter probes.
_STATION_ID_MIN = 1
_STATION_ID_MAX = 99
_SPEED_MULTIPLIER_MIN = 0.0  # exclusive: speed must be strictly positive
_SPEED_MULTIPLIER_MAX = 10.0
_AGV_COUNT_MIN = 1
_AGV_COUNT_MAX = 50


def _normalize_acceptance(value: Any) -> list[dict[str, Any]]:
    """Validate and normalize the optional F4 acceptance criteria array.

    Drops malformed entries rather than failing the turn, so a partly-bad LLM payload
    still runs the sim with whatever criteria are well-formed.
    """
    if not isinstance(value, list):
        raise ToolValidationError("acceptance must be an array")
    normalized: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        metric = entry.get("metric")
        comparator = entry.get("comparator")
        threshold = entry.get("threshold")
        if metric not in _ACCEPTANCE_METRICS:
            continue
        if comparator not in _ACCEPTANCE_COMPARATORS:
            continue
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            continue
        check: dict[str, Any] = {
            "metric": metric,
            "comparator": comparator,
            "threshold": float(threshold),
        }
        label = entry.get("label")
        check["label"] = label if isinstance(label, str) and label else f"{metric} {comparator} {threshold}"
        normalized.append(check)
    return normalized


class ToolRouter:
    def validate(self, tool_call: ToolCall, *, check_ranges: bool = False) -> ValidatedToolCall:
        contract = ROBOT_TOOL_CONTRACTS.get(tool_call.name)
        if contract is None:
            raise ToolValidationError(f"Unsupported tool: {tool_call.name}")
        missing = [field for field in contract.required if field not in tool_call.arguments]
        if missing:
            raise ToolValidationError(f"Missing tool arguments: {', '.join(missing)}")
        if "station_id" in tool_call.arguments and not isinstance(
            tool_call.arguments["station_id"], int
        ):
            raise ToolValidationError("station_id must be an integer")
        if "speed_multiplier" in tool_call.arguments and not isinstance(
            tool_call.arguments["speed_multiplier"], (int, float)
        ):
            raise ToolValidationError("speed_multiplier must be a number")
        if "priority" in tool_call.arguments and tool_call.arguments["priority"] not in {
            "normal",
            "high",
        }:
            raise ToolValidationError("priority must be normal or high")
        if "command_id" in tool_call.arguments and not isinstance(
            tool_call.arguments["command_id"], str
        ):
            raise ToolValidationError("command_id must be a string")
        if check_ranges:
            self._validate_ranges(tool_call)
        if "acceptance" in tool_call.arguments:
            tool_call.arguments["acceptance"] = _normalize_acceptance(
                tool_call.arguments["acceptance"]
            )
        return ValidatedToolCall(name=tool_call.name, arguments=dict(tool_call.arguments))

    def _validate_ranges(self, tool_call: ToolCall) -> None:
        """Phase-2-B Fix #2: reject out-of-range argument values (after type checks).

        Type-correct but semantically impossible values are rejected here so the
        validation layer can repair-retry or decline instead of dispatching them to
        UE5. ``bool`` is excluded because ``isinstance(True, int)`` is ``True``.
        """
        args = tool_call.arguments
        station_id = args.get("station_id")
        if isinstance(station_id, int) and not isinstance(station_id, bool):
            if not (_STATION_ID_MIN <= station_id <= _STATION_ID_MAX):
                raise ToolValidationError(
                    f"station_id {station_id} out of range "
                    f"({_STATION_ID_MIN}-{_STATION_ID_MAX})"
                )
        speed = args.get("speed_multiplier")
        if isinstance(speed, (int, float)) and not isinstance(speed, bool):
            if not (_SPEED_MULTIPLIER_MIN < speed <= _SPEED_MULTIPLIER_MAX):
                raise ToolValidationError(
                    f"speed_multiplier {speed} out of range "
                    f"(0 < x <= {_SPEED_MULTIPLIER_MAX})"
                )
        agv_count = args.get("agv_count")
        if agv_count is not None:
            if not isinstance(agv_count, int) or isinstance(agv_count, bool):
                raise ToolValidationError("agv_count must be an integer")
            if not (_AGV_COUNT_MIN <= agv_count <= _AGV_COUNT_MAX):
                raise ToolValidationError(
                    f"agv_count {agv_count} out of range "
                    f"({_AGV_COUNT_MIN}-{_AGV_COUNT_MAX})"
                )

    def ollama_tools(self) -> list[dict]:
        return [contract.to_ollama_tool() for contract in ROBOT_TOOL_CONTRACTS.values()]

    def user_facing_tools(self) -> list[dict]:
        """Tool list offered to the LLM when planning a user turn.

        Excludes internal-only tools (move_to_station) so a user cannot explicitly trigger
        them; the contracts remain valid for internal/agent-plan use via ``ollama_tools``.
        """
        return [
            contract.to_ollama_tool()
            for name, contract in ROBOT_TOOL_CONTRACTS.items()
            if name not in _INTERNAL_ONLY_TOOLS
        ]
