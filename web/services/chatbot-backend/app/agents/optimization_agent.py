from __future__ import annotations

from app.domain.optimization import (
    OptimizationGoal,
    OptimizationOutcome,
    parse_optimization_goal,
    search_optimal_agv_count,
)
from app.domain.process_model import simulate_run_kpis


class OptimizationAgent:
    """Goal-seeking agent: searches for the AGV count that meets an operator goal.

    Owns the observe → judge → decide loop. It parses the goal from the request and drives
    ``search_optimal_agv_count`` over the deterministic process model, so each candidate's KPIs
    (including the heatmap-derived bottleneck rate) are produced in-turn without a UE5 round-trip.
    Persistence, events and the chat report stay in the orchestrator.
    """

    def parse_goal(
        self,
        user_text: str,
        max_count: int | None = None,
    ) -> OptimizationGoal | None:
        return parse_optimization_goal(user_text, max_count=max_count)

    def search(self, goal: OptimizationGoal) -> OptimizationOutcome:
        return search_optimal_agv_count(goal, simulate_run_kpis)
