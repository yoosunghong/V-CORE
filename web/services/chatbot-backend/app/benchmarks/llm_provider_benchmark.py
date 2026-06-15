from __future__ import annotations

import asyncio
import csv
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from app.application.ports import LlmGateway
from app.domain.models import RobotCommandName, ToolCall
from app.tools.router import ToolRouter


@dataclass(frozen=True)
class BenchmarkPrompt:
    case_id: str
    prompt: str
    expected_tool: str | None
    notes: str = ""


@dataclass(frozen=True)
class PromptBenchmarkResult:
    provider: str
    case_id: str
    prompt: str
    expected_tool: str | None
    actual_tool: str | None
    tool_selection_correct: bool
    json_parse_success: bool
    schema_validation_success: bool
    repair_retry_used: bool
    rule_based_fallback_used: bool
    latency_ms: float
    attempts: list[dict[str, Any]]
    arguments: dict[str, Any] | None
    error: str | None = None


DEFAULT_BENCHMARK_PROMPTS: tuple[BenchmarkPrompt, ...] = (
    BenchmarkPrompt("process_status_query", "What is the current process status?", None),
    BenchmarkPrompt("start_simulation", "Start the simulation with 3 AGVs.", "start_simulation"),
    BenchmarkPrompt(
        "start_simulation_with_kpi_acceptance",
        "Start a simulation with 4 AGVs and accept only if throughput is at least 70 per hour, average wait is under 12 seconds, and collisions are zero.",
        "start_simulation",
    ),
    BenchmarkPrompt("stop_simulation", "Stop the running simulation.", "stop_simulation"),
    BenchmarkPrompt("abort_confirm", "Abort the current simulation now. Yes, confirm.", "stop_simulation"),
    BenchmarkPrompt("pause_resume", "Pause the simulation, then resume it when ready.", "pause_simulation"),
    BenchmarkPrompt("set_speed", "Set simulation speed to 1.5x.", "set_sim_speed"),
    BenchmarkPrompt("move_agv_to_station", "Move the AGV to station 2.", "move_to_station"),
    BenchmarkPrompt("run_station_task", "Run the task at station 3.", "run_station_task"),
    BenchmarkPrompt("inspect_station", "Inspect station 4.", "inspect_station"),
    BenchmarkPrompt("available_actions_query", "What actions are available for station 2?", None),
    BenchmarkPrompt("ambiguous_command", "Can you handle that one over there?", None),
)


def summarize_results(
    provider: str,
    prompt_results: Iterable[PromptBenchmarkResult],
    *,
    cold_start_latency_ms: float | None = None,
    memory_usage_bytes: int | None = None,
    preload_error: str | None = None,
) -> dict[str, Any]:
    rows = list(prompt_results)
    total = len(rows)
    latencies = [row.latency_ms for row in rows if row.error is None]
    return {
        "provider": provider,
        "prompt_count": total,
        "json_parse_success_rate": _rate(row.json_parse_success for row in rows),
        "schema_validation_success_rate": _rate(row.schema_validation_success for row in rows),
        "tool_selection_accuracy": _rate(row.tool_selection_correct for row in rows),
        "repair_retry_rate": _rate(row.repair_retry_used for row in rows),
        "rule_based_fallback_rate": _rate(row.rule_based_fallback_used for row in rows),
        "average_latency_ms": _avg(latencies),
        "p95_latency_ms": _p95(latencies),
        "stddev_latency_ms": _stddev(latencies),
        "first_request_latency_ms": latencies[0] if latencies else None,
        "warm_average_latency_ms": _avg(latencies[1:]) if len(latencies) > 1 else None,
        "cold_start_latency_ms": cold_start_latency_ms,
        "preload_error": preload_error,
        "memory_usage_bytes": memory_usage_bytes,
        "errors": [asdict(row) for row in rows if row.error],
    }


async def run_provider_benchmark(
    provider: str,
    gateway: LlmGateway,
    prompts: Iterable[BenchmarkPrompt] = DEFAULT_BENCHMARK_PROMPTS,
    *,
    preload: bool = True,
) -> dict[str, Any]:
    cold_start_latency_ms: float | None = None
    preload_error: str | None = None
    if preload and hasattr(gateway, "preload"):
        start = time.perf_counter()
        try:
            await gateway.preload(f"bench-{provider}-preload")  # type: ignore[attr-defined]
            cold_start_latency_ms = _elapsed_ms(start)
        except Exception as exc:
            preload_error = str(exc)

    rows: list[PromptBenchmarkResult] = []
    for index, prompt in enumerate(prompts, start=1):
        rows.append(await _run_prompt(provider, gateway, prompt, index))

    return {
        "summary": summarize_results(
            provider,
            rows,
            cold_start_latency_ms=cold_start_latency_ms,
            memory_usage_bytes=get_current_process_memory_bytes(),
            preload_error=preload_error,
        ),
        "prompts": [asdict(row) for row in rows],
    }


def write_benchmark_outputs(
    output_dir: str | Path,
    results_by_provider: dict[str, dict[str, Any]],
) -> dict[str, str]:
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    json_path = path / "llm_provider_comparison.json"
    csv_path = path / "llm_provider_comparison.csv"

    payload = {
        "generated_at_unix": time.time(),
        "results": results_by_provider,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    rows: list[dict[str, Any]] = []
    for provider_result in results_by_provider.values():
        rows.extend(provider_result.get("prompts", []))
    fieldnames = [
        "provider",
        "case_id",
        "expected_tool",
        "actual_tool",
        "tool_selection_correct",
        "json_parse_success",
        "schema_validation_success",
        "repair_retry_used",
        "rule_based_fallback_used",
        "latency_ms",
        "error",
        "prompt",
        "arguments",
        "attempts",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    **{field: row.get(field) for field in fieldnames},
                    "arguments": json.dumps(row.get("arguments"), ensure_ascii=False),
                    "attempts": json.dumps(row.get("attempts"), ensure_ascii=False),
                }
            )

    return {"json": str(json_path), "csv": str(csv_path)}


async def _run_prompt(
    provider: str,
    gateway: LlmGateway,
    prompt: BenchmarkPrompt,
    index: int,
) -> PromptBenchmarkResult:
    start = time.perf_counter()
    tool_call: ToolCall | None = None
    error: str | None = None
    try:
        tool_call = await gateway.propose_tool_call(
            prompt.prompt,
            None,
            f"bench-{provider}-{index:02d}-{prompt.case_id}",
        )
    except Exception as exc:
        error = str(exc)
    latency_ms = _elapsed_ms(start)
    attempts = list(getattr(gateway, "last_tool_attempts", []) or [])
    actual_tool = tool_call.name.value if tool_call else None
    llm_valid = any(attempt.get("valid") is True for attempt in attempts)
    return PromptBenchmarkResult(
        provider=provider,
        case_id=prompt.case_id,
        prompt=prompt.prompt,
        expected_tool=prompt.expected_tool,
        actual_tool=actual_tool,
        tool_selection_correct=actual_tool == prompt.expected_tool,
        json_parse_success=_json_parse_succeeded(attempts),
        schema_validation_success=llm_valid,
        repair_retry_used=len(attempts) > 1,
        rule_based_fallback_used=tool_call is not None and not llm_valid,
        latency_ms=latency_ms,
        attempts=attempts,
        arguments=tool_call.arguments if tool_call else None,
        error=error,
    )


def _json_parse_succeeded(attempts: list[dict[str, Any]]) -> bool:
    if any(attempt.get("valid") is True for attempt in attempts):
        return True
    if not attempts:
        return False
    parse_error_tokens = (
        "non-json",
        "invalid json",
        "not valid json",
        "json response must be an object",
        "no tool call",
    )
    return any(
        attempt.get("valid") is False
        and not any(token in str(attempt.get("error", "")).lower() for token in parse_error_tokens)
        for attempt in attempts
    )


def _rate(values: Iterable[bool]) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for value in items if value) / len(items)


def _avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _stddev(values: list[float]) -> float | None:
    return statistics.pstdev(values) if len(values) > 1 else 0.0 if values else None


def _p95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return ordered[index]


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000.0, 3)


def get_current_process_memory_bytes() -> int | None:
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(usage * 1024)
    except Exception:
        return _windows_working_set_bytes()


def _windows_working_set_bytes() -> int | None:
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(ProcessMemoryCounters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), counters.cb
        )
        return int(counters.WorkingSetSize) if ok else None
    except Exception:
        return None


def validate_expected_tools(prompts: Iterable[BenchmarkPrompt]) -> None:
    tool_names = {name.value for name in RobotCommandName}
    for prompt in prompts:
        if prompt.expected_tool is not None and prompt.expected_tool not in tool_names:
            raise ValueError(f"Unknown expected tool for {prompt.case_id}: {prompt.expected_tool}")
    ToolRouter()


def run_async(coro: Any) -> Any:
    return asyncio.run(coro)
