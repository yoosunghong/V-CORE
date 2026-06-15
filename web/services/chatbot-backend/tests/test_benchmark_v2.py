from __future__ import annotations

from app.benchmarks.benchmark_v2 import aggregate_cell, failure_gallery, score_case
from app.benchmarks.case_generator import build_all_cases
from app.benchmarks.cases_v2 import (
    CATEGORIES,
    BenchmarkCaseV2,
    args_match,
    load_cases_dir,
    values_match,
    wilson_rate,
)
from app.domain.models import RobotCommandName, ToolCall
from pathlib import Path

CASES_DIR = Path(__file__).resolve().parents[4] / "docs" / "benchmark" / "cases" / "v2"


def _tool(name: str, **args) -> ToolCall:
    return ToolCall(name=RobotCommandName(name), arguments=dict(args))


# --- value / arg matching ---------------------------------------------------


def test_values_match_numeric_string_coercion():
    assert values_match(3, "3")
    assert values_match(2.0, 2)
    assert not values_match(3, "4")


def test_values_match_nested_acceptance_subset():
    expected = [{"metric": "collision_count", "comparator": "==", "threshold": 0}]
    actual = [
        {"metric": "throughput", "comparator": ">=", "threshold": 70},
        {"metric": "collision_count", "comparator": "==", "threshold": 0, "label": "x"},
    ]
    assert values_match(expected, actual)


def test_args_match_modes():
    assert args_match({"station_id": 3}, {"station_id": 3, "priority": "normal"}, "subset")
    assert not args_match({"station_id": 3}, {"station_id": 3, "priority": "high"}, "exact")
    assert args_match({"station_id": 3}, {"station_id": 3}, "exact")
    assert args_match({"station_id": 3}, {"station_id": 99}, "ignore")


# --- Wilson CI --------------------------------------------------------------


def test_wilson_rate_bounds():
    r = wilson_rate(7, 12)
    assert 0.0 <= r.ci_low < r.rate < r.ci_high <= 1.0
    assert wilson_rate(0, 0).total == 0


# --- score_case -------------------------------------------------------------


def _score(case: BenchmarkCaseV2, tool_call, attempts):
    return score_case(
        case, tool_call, attempts, cell="A2", provider="ollama", layer="on",
        repeat=1, latency_ms=1.0, error=None,
    )


def test_score_positive_correct():
    case = BenchmarkCaseV2("c1", "parameter_extraction", "en", "Move to station 7",
                           "move_to_station", {"station_id": 7}, "exact")
    res = _score(case, _tool("move_to_station", station_id=7), [{"attempt": 1, "valid": True}])
    assert res.tool_correct and res.args_correct and res.task_success
    assert res.output_path == "json_content"


def test_score_wrong_args_is_failure():
    case = BenchmarkCaseV2("c2", "parameter_extraction", "en", "Move to station 7",
                           "move_to_station", {"station_id": 7}, "exact")
    res = _score(case, _tool("move_to_station", station_id=3), [{"attempt": 1, "valid": True}])
    assert res.tool_correct and not res.args_correct and not res.task_success


def test_score_negative_control_declined():
    case = BenchmarkCaseV2("c3", "negative_control", "en", "Hi", None)
    res = _score(case, None, [{"attempt": 1, "valid": False, "error": "no tool call"}])
    assert res.tool_correct and res.task_success and res.clarification_appropriate


def test_score_negative_control_overfire_fails():
    case = BenchmarkCaseV2("c4", "negative_control", "en", "Hi", None)
    res = _score(case, _tool("inspect_station", station_id=2), [{"attempt": 1, "valid": True}])
    assert not res.tool_correct and not res.task_success


def test_score_fallback_used_marks_path():
    case = BenchmarkCaseV2("c5", "positive_invocation", "en", "Pause", "pause_simulation",
                           None, "ignore")
    # No valid LLM attempt but a tool was returned -> rule-based fallback.
    res = _score(case, _tool("pause_simulation"), [{"attempt": 1, "valid": False, "error": "bad"}])
    assert res.rule_based_fallback_used and res.output_path == "rule_based_fallback"
    assert res.task_success


# --- generator integrity ----------------------------------------------------


def test_generator_cases_are_valid():
    cases = build_all_cases()
    tool_names = {n.value for n in RobotCommandName}
    ids = set()
    per_cat = {c: 0 for c in CATEGORIES}
    for case in cases:
        assert case.case_id not in ids, f"dup {case.case_id}"
        ids.add(case.case_id)
        per_cat[case.category] += 1
        if case.expected_tool is not None:
            assert case.expected_tool in tool_names, case.case_id
    assert all(count >= 10 for count in per_cat.values()), per_cat


def test_committed_suite_loads_and_matches_generator():
    on_disk = load_cases_dir(CASES_DIR)
    generated = build_all_cases()
    assert len(on_disk) == len(generated)
    assert {c.case_id for c in on_disk} == {c.case_id for c in generated}


def test_aggregate_and_gallery_smoke():
    case_ok = BenchmarkCaseV2("ok", "positive_invocation", "en", "Stop", "stop_simulation",
                              None, "ignore")
    case_bad = BenchmarkCaseV2("bad", "parameter_extraction", "en", "Move to 7",
                               "move_to_station", {"station_id": 7}, "exact")
    rows = [
        _score(case_ok, _tool("stop_simulation"), [{"attempt": 1, "valid": True}]),
        _score(case_bad, _tool("move_to_station", station_id=1), [{"attempt": 1, "valid": True}]),
    ]
    agg = aggregate_cell("A2", rows)
    assert agg["rates"]["task_success"]["total"] == 2
    assert len(failure_gallery(rows)) == 1
