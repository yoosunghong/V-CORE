from __future__ import annotations

import asyncio

from app.domain.optimization import (
    OptimizationGoal,
    is_optimize_request,
    parse_optimization_goal,
    search_optimal_agv_count,
)
from app.domain.models import DomainEvent
from app.domain.process_model import bottleneck_rate_from_heatmap, simulate_run_kpis
from app.infrastructure.container import AppContainer

GOAL_MESSAGE = "병목률 30% 이하를 만족하는 최적 AGV 대수를 찾아줘"


# --- process model -----------------------------------------------------------------


def test_bottleneck_rate_is_derived_from_the_heatmap() -> None:
    # The KPI's bottleneck_rate must equal recomputing it from the embedded grid.
    kpis = simulate_run_kpis(3)
    recomputed = bottleneck_rate_from_heatmap(
        kpis["heatmap_grid"], kpis["heatmap_res_x"], kpis["heatmap_res_y"]
    )
    assert kpis["bottleneck_rate"] == recomputed


def test_bottleneck_rate_grows_with_agv_count() -> None:
    rates = [simulate_run_kpis(n)["bottleneck_rate"] for n in (1, 2, 3)]
    assert rates[0] < rates[1] < rates[2]


def test_scenario_threshold_lands_between_two_and_three_agvs() -> None:
    # The demo's premise: 3 AGVs exceed 30% bottleneck, 2 AGVs satisfy it.
    assert simulate_run_kpis(3)["bottleneck_rate"] > 30.0
    assert simulate_run_kpis(2)["bottleneck_rate"] <= 30.0


def test_empty_grid_rate_is_zero() -> None:
    assert bottleneck_rate_from_heatmap([], 0, 0) == 0.0


def test_bottleneck_rate_ignores_untraversed_zero_cells() -> None:
    assert bottleneck_rate_from_heatmap([1.0, 0.0, 0.0, 0.0], 2, 2) == 100.0


def test_bottleneck_rate_uses_traversed_mask_when_present() -> None:
    grid = [1.0, 0.2, 0.0, 0.0]
    traversed = [True, True, False, False]
    assert bottleneck_rate_from_heatmap(grid, 2, 2, traversed) == 50.0


# --- goal parsing ------------------------------------------------------------------


def test_is_optimize_request_needs_verb_and_metric() -> None:
    assert is_optimize_request(GOAL_MESSAGE) is True
    assert is_optimize_request("AGV 3대로 시뮬레이션 돌려줘") is False  # no optimize verb
    assert is_optimize_request("최적 속도를 찾아줘") is False  # no bottleneck metric


def test_parse_goal_extracts_threshold_and_default_comparator() -> None:
    goal = parse_optimization_goal(GOAL_MESSAGE)
    assert goal is not None
    assert goal.metric == "bottleneck_rate"
    assert goal.comparator == "<="
    assert goal.threshold == 30.0


# --- search loop -------------------------------------------------------------------


def test_search_finds_largest_satisfying_count() -> None:
    goal = OptimizationGoal(threshold=30.0)
    outcome = search_optimal_agv_count(goal, simulate_run_kpis)
    assert outcome.optimal_count == 2
    # Stops at the first satisfying candidate going high→low: tries 3, then 2.
    assert [s.agv_count for s in outcome.steps] == [3, 2]
    assert outcome.steps[0].satisfied is False
    assert outcome.steps[1].satisfied is True


def test_search_reports_infeasible_when_nothing_satisfies() -> None:
    goal = OptimizationGoal(threshold=1.0)  # impossibly strict
    outcome = search_optimal_agv_count(goal, simulate_run_kpis)
    assert outcome.optimal_count is None
    assert [s.agv_count for s in outcome.steps] == [3, 2, 1]


# --- orchestrator integration ------------------------------------------------------


def test_optimize_request_routes_to_optimize_agvs() -> None:
    orch = AppContainer().chat
    route, source = asyncio.run(orch._classify_route(GOAL_MESSAGE, "corr"))
    assert (route, source) == ("optimize_agvs", "keyword")


def test_end_to_end_loop_reports_optimum_and_persists_runs() -> None:
    orch = AppContainer().chat

    async def _run() -> tuple[str, int]:
        assistant, _command_id, _status, _events = await orch.handle_user_message(
            session_id="session_opt",
            user_text=GOAL_MESSAGE,
        )
        runs = await orch._repository.list_runs()
        return assistant.content, len(runs)

    content, run_count = asyncio.run(_run())
    assert "최적 결과: AGV 2대" in content
    # Search bound comes from the cell fleet size (mock telemetry → config fallback of 5),
    # so the rejected high candidates are shown and one run is persisted per tried candidate.
    assert "AGV 5대 → 병목률" in content
    assert "AGV 3대 → 병목률" in content
    assert run_count == 4  # tries 5, 4, 3 (all fail), then 2 (passes)


def test_live_loop_drives_real_runs_and_converges() -> None:
    """The live loop issues a real start_simulation per candidate and waits for its KPIs.

    UE5 is stood in for: a fake consumer watches for each 'running' iteration and publishes the
    matching robot.command.completed with a real heatmap grid (bottleneck_rate omitted, exactly
    like UE5), so the loop must derive the rate from the heatmap and decide the next candidate.
    """
    from app.domain.optimization import OptimizationGoal

    orch = AppContainer().chat
    orch._auto_complete_commands = False  # force the live (background) path

    async def main() -> list[str]:
        fake_ue5 = await orch._events.subscribe("session_live")
        loop_task = asyncio.create_task(
            orch._run_agv_optimization_live("session_live", "corr", OptimizationGoal(threshold=30.0))
        )
        responded = 0
        while responded < 2:  # tries 3 (fail) then 2 (pass) → 2 runs
            event = await asyncio.wait_for(fake_ue5.get(), timeout=5.0)
            if event.event_type == "agent.optimize.iteration" and event.payload.get("phase") == "running":
                count = event.payload["agv_count"]
                kpis = simulate_run_kpis(count)
                kpis.pop("bottleneck_rate")  # UE5 sends the grid, not the rate
                await orch._events.publish(
                    DomainEvent(
                        event_type="robot.command.completed",
                        correlation_id="corr",
                        session_id="session_live",
                        command_id=event.command_id,
                        payload={"kpis": kpis},
                    )
                )
                responded += 1
        await asyncio.wait_for(loop_task, timeout=5.0)
        await orch._events.unsubscribe("session_live", fake_ue5)
        msgs = await orch._repository.list_messages("session_live")
        return [m.content for m in msgs]

    contents = asyncio.run(main())
    assert any("최적 결과: AGV 2대" in c for c in contents)
