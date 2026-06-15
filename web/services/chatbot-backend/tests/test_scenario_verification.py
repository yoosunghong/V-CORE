from __future__ import annotations

import pytest

from app.domain.evaluation import ComparedRun, build_run_comparison
from app.domain.models import RobotCommandName, ToolCall, format_verdict_summary
from app.tools.contracts import ToolValidationError
from app.tools.router import ToolRouter


def test_format_verdict_summary_pass() -> None:
    summary = format_verdict_summary(
        {"passed": True, "passed_labels": ["throughput >= 70/h"], "failed_labels": []}
    )
    assert summary is not None
    assert "PASS" in summary
    assert "throughput >= 70/h" in summary


def test_format_verdict_summary_fail_lists_failed() -> None:
    summary = format_verdict_summary(
        {
            "passed": False,
            "passed_labels": ["throughput >= 70/h"],
            "failed_labels": ["collisions == 0"],
        }
    )
    assert summary is not None
    assert "FAIL" in summary
    assert "collisions == 0" in summary


def test_format_verdict_summary_ignores_empty() -> None:
    assert format_verdict_summary(None) is None
    assert format_verdict_summary({}) is None
    assert format_verdict_summary({"passed": True, "passed_labels": [], "failed_labels": []}) is None


def test_router_normalizes_acceptance_and_defaults_label() -> None:
    router = ToolRouter()
    validated = router.validate(
        ToolCall(
            name=RobotCommandName.START_SIMULATION,
            arguments={
                "agv_count": 4,
                "acceptance": [
                    {"metric": "throughput", "comparator": ">=", "threshold": 70},
                    {"label": "no crashes", "metric": "collision_count", "comparator": "==", "threshold": 0},
                ],
            },
        )
    )
    acceptance = validated.arguments["acceptance"]
    assert len(acceptance) == 2
    assert acceptance[0]["label"]  # auto-filled
    assert acceptance[0]["threshold"] == 70.0
    assert acceptance[1]["label"] == "no crashes"


def test_router_drops_malformed_acceptance_entries() -> None:
    router = ToolRouter()
    validated = router.validate(
        ToolCall(
            name=RobotCommandName.START_SIMULATION,
            arguments={
                "acceptance": [
                    {"metric": "bogus", "comparator": ">=", "threshold": 1},  # bad metric
                    {"metric": "uptime_ratio", "comparator": "~", "threshold": 1},  # bad comparator
                    {"metric": "active_agvs", "comparator": ">=", "threshold": "x"},  # bad threshold
                    {"metric": "avg_wait_sec", "comparator": "<=", "threshold": 12},  # good
                ],
            },
        )
    )
    acceptance = validated.arguments["acceptance"]
    assert len(acceptance) == 1
    assert acceptance[0]["metric"] == "avg_wait_sec"


def test_router_rejects_non_list_acceptance() -> None:
    router = ToolRouter()
    with pytest.raises(ToolValidationError):
        router.validate(
            ToolCall(
                name=RobotCommandName.START_SIMULATION,
                arguments={"acceptance": {"metric": "throughput"}},
            )
        )


def test_run_comparison_picks_metric_winner() -> None:
    # B is better on throughput (higher) and avg_wait (lower) and uptime; A wins only collision.
    run_a = ComparedRun(
        label="A안",
        kpis={"throughput": 60.0, "avg_wait_time": 18.0, "collision_risk": 0.1, "uptime": 0.9},
    )
    run_b = ComparedRun(
        label="B안",
        kpis={"throughput": 90.0, "avg_wait_time": 8.0, "collision_risk": 0.5, "uptime": 0.97},
    )
    comparison = build_run_comparison(run_a, run_b)
    assert comparison is not None
    assert comparison.winner_label == "B안"
    assert "3/4" in comparison.headline


def test_run_comparison_acceptance_verdict_overrides_metric_tally() -> None:
    # A wins every metric, but only B passed acceptance → B is the winner.
    run_a = ComparedRun(
        label="A안",
        kpis={"throughput": 99.0, "avg_wait_time": 5.0},
        verdict={"passed": False, "passed_labels": [], "failed_labels": ["collisions == 0"]},
    )
    run_b = ComparedRun(
        label="B안",
        kpis={"throughput": 70.0, "avg_wait_time": 9.0},
        verdict={"passed": True, "passed_labels": ["collisions == 0"], "failed_labels": []},
    )
    comparison = build_run_comparison(run_a, run_b)
    assert comparison is not None
    assert comparison.winner_label == "B안"
    assert "수용 기준을 통과" in comparison.headline


def test_run_comparison_tie_has_no_winner() -> None:
    run_a = ComparedRun(label="A안", kpis={"throughput": 80.0, "avg_wait_time": 10.0})
    run_b = ComparedRun(label="B안", kpis={"throughput": 90.0, "avg_wait_time": 12.0})
    comparison = build_run_comparison(run_a, run_b)
    assert comparison is not None
    assert comparison.winner_label is None
    assert "박빙" in comparison.headline


def test_run_comparison_returns_none_without_shared_kpis() -> None:
    assert build_run_comparison(ComparedRun("A안", {}), ComparedRun("B안", {})) is None
