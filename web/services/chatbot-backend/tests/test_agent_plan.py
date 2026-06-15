from __future__ import annotations

from app.infrastructure.container import AppContainer


def _orch():
    return AppContainer().chat


def test_stop_and_cancel_plans_are_two_steps() -> None:
    orch = _orch()
    stop = orch._plan_for_request("시뮬레이션 정지해줘")
    cancel = orch._plan_for_request("방금 명령 취소해줘")
    assert stop is not None and len(stop[0]) == 2
    assert cancel is not None and len(cancel[0]) == 2


def test_start_plan_is_three_steps_and_optimize_is_five() -> None:
    orch = _orch()
    start = orch._plan_for_request("시뮬레이션 시작해줘")
    optimize = orch._plan_for_request("병목률 30% 이하 최적 AGV 대수를 찾아줘")
    assert start is not None and len(start[0]) == 3
    assert optimize is not None and len(optimize[0]) == 5


def test_variable_requests_defer_to_the_llm_planner() -> None:
    # A station task is genuinely variable, so no deterministic plan is canned — it falls through
    # to the LLM planner (returns None here).
    orch = _orch()
    assert orch._plan_for_request("2번 스테이션에서 작업해줘") is None


def test_deterministic_plans_never_leak_route_identifiers() -> None:
    orch = _orch()
    leaks = ("command_cancel", "station_task", "run_station_task", "move_to_station", "_simulation")
    for message in ("시뮬레이션 정지해줘", "방금 명령 취소해줘", "시뮬레이션 시작해줘"):
        plan = orch._plan_for_request(message)
        assert plan is not None
        joined = " ".join(plan[0])
        assert not any(token in joined for token in leaks)
