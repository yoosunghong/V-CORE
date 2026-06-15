from __future__ import annotations

import asyncio
import json

from app.benchmarks.llm_provider_benchmark import (
    PromptBenchmarkResult,
    _json_parse_succeeded,
    run_provider_benchmark,
    summarize_results,
    write_benchmark_outputs,
)
from app.domain.models import RobotCommandName, ToolCall


def test_json_parse_success_counts_schema_errors_as_parseable() -> None:
    assert _json_parse_succeeded(
        [{"attempt": 1, "valid": False, "error": "speed_multiplier must be a number"}]
    )
    assert not _json_parse_succeeded(
        [{"attempt": 1, "valid": False, "error": "Ollama returned invalid JSON"}]
    )


def test_summarize_results_calculates_rates_and_latency_stats() -> None:
    rows = [
        PromptBenchmarkResult(
            provider="fake",
            case_id="a",
            prompt="a",
            expected_tool="start_simulation",
            actual_tool="start_simulation",
            tool_selection_correct=True,
            json_parse_success=True,
            schema_validation_success=True,
            repair_retry_used=False,
            rule_based_fallback_used=False,
            latency_ms=10.0,
            attempts=[{"valid": True}],
            arguments={},
        ),
        PromptBenchmarkResult(
            provider="fake",
            case_id="b",
            prompt="b",
            expected_tool="set_sim_speed",
            actual_tool="set_sim_speed",
            tool_selection_correct=True,
            json_parse_success=True,
            schema_validation_success=False,
            repair_retry_used=True,
            rule_based_fallback_used=True,
            latency_ms=30.0,
            attempts=[{"valid": False}, {"valid": False}],
            arguments={"speed_multiplier": 2.0},
        ),
    ]

    summary = summarize_results("fake", rows, cold_start_latency_ms=5.0, memory_usage_bytes=123)

    assert summary["tool_selection_accuracy"] == 1.0
    assert summary["schema_validation_success_rate"] == 0.5
    assert summary["repair_retry_rate"] == 0.5
    assert summary["average_latency_ms"] == 20.0
    assert summary["p95_latency_ms"] == 30.0
    assert summary["warm_average_latency_ms"] == 30.0
    assert summary["cold_start_latency_ms"] == 5.0
    assert summary["memory_usage_bytes"] == 123


def test_write_benchmark_outputs_creates_json_and_csv(tmp_path) -> None:
    provider_result = {
        "summary": {"provider": "fake"},
        "prompts": [
            {
                "provider": "fake",
                "case_id": "start",
                "prompt": "start",
                "expected_tool": "start_simulation",
                "actual_tool": "start_simulation",
                "tool_selection_correct": True,
                "json_parse_success": True,
                "schema_validation_success": True,
                "repair_retry_used": False,
                "rule_based_fallback_used": False,
                "latency_ms": 1.0,
                "attempts": [{"valid": True}],
                "arguments": {},
                "error": None,
            }
        ],
    }

    paths = write_benchmark_outputs(tmp_path, {"fake": provider_result})

    assert json.loads((tmp_path / "llm_provider_comparison.json").read_text(encoding="utf-8"))[
        "results"
    ]["fake"]["summary"]["provider"] == "fake"
    assert "provider,case_id" in (tmp_path / "llm_provider_comparison.csv").read_text(
        encoding="utf-8"
    )
    assert paths["json"].endswith("llm_provider_comparison.json")


def test_run_provider_benchmark_marks_rule_based_fallback() -> None:
    class FakeGateway:
        def __init__(self) -> None:
            self.last_tool_attempts = []

        async def preload(self, correlation_id: str = "startup-preload") -> None:
            return None

        async def propose_tool_call(self, user_message: str, station, correlation_id: str):
            self.last_tool_attempts = [
                {"attempt": 1, "valid": False, "error": "Ollama returned no tool call"}
            ]
            return ToolCall(name=RobotCommandName.START_SIMULATION, arguments={})

    result = asyncio.run(
        run_provider_benchmark(
            "fake",
            FakeGateway(),
            prompts=[
                type(
                    "Prompt",
                    (),
                    {
                        "case_id": "start",
                        "prompt": "start simulation",
                        "expected_tool": "start_simulation",
                    },
                )()
            ],
            preload=False,
        )
    )

    row = result["prompts"][0]
    assert row["rule_based_fallback_used"] is True
    assert row["schema_validation_success"] is False
    assert result["summary"]["rule_based_fallback_rate"] == 1.0


def test_run_provider_benchmark_records_preload_error() -> None:
    class FakeGateway:
        last_tool_attempts = []

        async def preload(self, correlation_id: str = "startup-preload") -> None:
            raise RuntimeError("provider unavailable")

        async def propose_tool_call(self, user_message: str, station, correlation_id: str):
            return None

    result = asyncio.run(
        run_provider_benchmark(
            "fake",
            FakeGateway(),
            prompts=[
                type(
                    "Prompt",
                    (),
                    {"case_id": "ambiguous", "prompt": "maybe", "expected_tool": None},
                )()
            ],
            preload=True,
        )
    )

    assert result["summary"]["preload_error"] == "provider unavailable"
    assert result["prompts"][0]["tool_selection_correct"] is True
