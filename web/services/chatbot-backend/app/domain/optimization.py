from __future__ import annotations

"""Goal parsing and the goal-seeking search for the agentic optimization loop.

Pure domain logic: no I/O, no persistence. ``parse_optimization_goal`` turns an operator
request into an :class:`OptimizationGoal`; ``search_optimal_agv_count`` runs the
observe → judge → decide loop over a KPI simulator, returning every candidate it tried and
the chosen optimum. The orchestrator layer is responsible for persistence, events and the
chat report.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

# Default search bounds. The upper bound is normally the cell's authored AGV count, which the
# orchestrator reads live from UE5 (/sim/status max_agvs) and passes into parse_optimization_goal.
# _DEFAULT_MAX_AGV is only a last-resort fallback for direct goal construction (e.g. unit tests).
_DEFAULT_MIN_AGV = 1
_DEFAULT_MAX_AGV = 3
_DEFAULT_THRESHOLD = 30.0

# Words that signal "search for the best configuration" rather than "run this once".
_OPTIMIZE_KEYWORDS = (
    "최적",
    "최적화",
    "적정",
    "찾아",
    "찾아줘",
    "찾아서",
    "몇 대",
    "몇대",
    "optimal",
    "optimize",
    "optimum",
    "best number",
    "how many",
)
# Only the bottleneck metric is searchable today; presence also disambiguates the intent.
_BOTTLENECK_KEYWORDS = ("병목", "bottleneck")


@dataclass(frozen=True)
class OptimizationGoal:
    """A parsed 'find the best AGV count' goal."""

    metric: str = "bottleneck_rate"
    comparator: str = "<="
    threshold: float = _DEFAULT_THRESHOLD
    min_count: int = _DEFAULT_MIN_AGV
    max_count: int = _DEFAULT_MAX_AGV
    label: str = ""


@dataclass(frozen=True)
class OptimizationStep:
    """One observed candidate in the search."""

    agv_count: int
    metric_value: float
    satisfied: bool
    kpis: dict[str, Any]


@dataclass
class OptimizationOutcome:
    goal: OptimizationGoal
    steps: list[OptimizationStep] = field(default_factory=list)
    optimal_count: int | None = None


def is_optimize_request(text: str) -> bool:
    """True when the text asks to *search* for the best AGV count by bottleneck rate."""
    normalized = text.lower()
    has_verb = any(keyword in normalized for keyword in _OPTIMIZE_KEYWORDS)
    has_metric = any(keyword in normalized for keyword in _BOTTLENECK_KEYWORDS)
    return has_verb and has_metric


def _parse_comparator(text: str) -> str:
    normalized = text.lower()
    if any(token in normalized for token in ("이상", "초과", ">=", "above", "at least", "넘", "이상으로")):
        return ">="
    # Default to "<=" — a bottleneck goal is virtually always an upper bound.
    return "<="


def parse_optimization_goal(
    text: str,
    max_count: int | None = None,
) -> OptimizationGoal | None:
    """Extract an :class:`OptimizationGoal` from the request, or None if it isn't one.

    ``max_count`` sets the search upper bound — the orchestrator passes the cell's live AGV
    fleet size here so the search tracks the real UE5 cell rather than a fixed constant.
    """
    if not is_optimize_request(text):
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    threshold = float(match.group(1)) if match else _DEFAULT_THRESHOLD
    comparator = _parse_comparator(text)
    label = f"병목률 {threshold:g}% {'이상' if comparator == '>=' else '이하'}"
    bound = max_count if max_count and max_count > 0 else _DEFAULT_MAX_AGV
    return OptimizationGoal(
        metric="bottleneck_rate",
        comparator=comparator,
        threshold=threshold,
        max_count=bound,
        label=label,
    )


def goal_satisfied(value: float, goal: OptimizationGoal) -> bool:
    if goal.comparator == ">=":
        return value >= goal.threshold
    if goal.comparator == "==":
        return value == goal.threshold
    return value <= goal.threshold


def search_optimal_agv_count(
    goal: OptimizationGoal,
    simulate: Callable[[int], dict[str, Any]],
) -> OptimizationOutcome:
    """Find the largest AGV count whose metric satisfies the goal.

    Iterates candidates from ``max_count`` down to ``min_count``. The bottleneck rate is
    monotonic in AGV count, so the first (highest) satisfying candidate is the optimum and the
    loop stops there — the agent decides its own next action (try one fewer AGV) and when the
    goal is met. Every candidate it observes is recorded for the report.
    """
    outcome = OptimizationOutcome(goal=goal)
    for count in range(goal.max_count, goal.min_count - 1, -1):
        kpis = simulate(count)
        value = float(kpis.get(goal.metric, 0.0))
        satisfied = goal_satisfied(value, goal)
        outcome.steps.append(
            OptimizationStep(agv_count=count, metric_value=value, satisfied=satisfied, kpis=kpis)
        )
        if satisfied:
            outcome.optimal_count = count
            break
    return outcome
