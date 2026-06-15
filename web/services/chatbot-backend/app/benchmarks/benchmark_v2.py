"""Phase-2 v2 benchmark: argument-level scoring, repeated trials with CIs, and the
2x2 validation-layer ablation (plan deliverables 2 & 3).

A *cell* is one (provider, layer) configuration — A1/A2 (Ollama off/on) and
B1/B2 (llama.cpp off/on). Each case is run R times in randomized order; every
reported rate carries a Wilson 95% CI so we never over-claim from a thin sample.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from app.application.ports import LlmGateway
from app.benchmarks.cases_v2 import (
    BenchmarkCaseV2,
    CATEGORIES,
    args_match,
    percentiles,
    rate_from_flags,
)
from app.benchmarks.llm_provider_benchmark import _json_parse_succeeded
from app.domain.models import ToolCall


@dataclass(frozen=True)
class CaseRunResult:
    cell: str
    provider: str
    layer: str  # "off" | "on"
    case_id: str
    category: str
    lang: str
    repeat: int
    prompt: str
    expected_tool: str | None
    actual_tool: str | None
    tool_correct: bool
    args_correct: bool
    json_parse_success: bool
    schema_validation_success: bool
    repair_retry_used: bool
    rule_based_fallback_used: bool
    clarification_applicable: bool
    clarification_appropriate: bool
    task_success: bool
    latency_ms: float
    attempt_count: int
    output_path: str
    arguments: dict[str, Any] | None
    error: str | None = None


def score_case(
    case: BenchmarkCaseV2,
    tool_call: ToolCall | None,
    attempts: list[dict[str, Any]],
    *,
    cell: str,
    provider: str,
    layer: str,
    repeat: int,
    latency_ms: float,
    error: str | None,
) -> CaseRunResult:
    actual_tool = tool_call.name.value if tool_call else None
    actual_args = tool_call.arguments if tool_call else None
    llm_valid = any(attempt.get("valid") is True for attempt in attempts)
    repair_retry_used = len(attempts) > 1
    fallback_used = tool_call is not None and not llm_valid

    if case.expected_tool is None:
        tool_correct = actual_tool is None
        args_correct = tool_correct
    else:
        allowed = {case.expected_tool, *case.accept_alternatives}
        tool_correct = actual_tool in allowed
        args_correct = tool_correct and args_match(
            case.expected_args, actual_args, case.arg_match
        )

    clarification_applicable = case.expect_clarification or case.expected_tool is None
    clarification_appropriate = clarification_applicable and actual_tool is None

    task_success = tool_correct and args_correct

    if fallback_used:
        output_path = "rule_based_fallback"
    elif llm_valid and any(a.get("via") == "tool_calls" for a in attempts):
        output_path = "tool_calls"
    elif llm_valid:
        output_path = "json_content"
    else:
        output_path = "none"

    return CaseRunResult(
        cell=cell,
        provider=provider,
        layer=layer,
        case_id=case.case_id,
        category=case.category,
        lang=case.lang,
        repeat=repeat,
        prompt=case.prompt,
        expected_tool=case.expected_tool,
        actual_tool=actual_tool,
        tool_correct=tool_correct,
        args_correct=args_correct,
        json_parse_success=_json_parse_succeeded(attempts),
        schema_validation_success=llm_valid,
        repair_retry_used=repair_retry_used,
        rule_based_fallback_used=fallback_used,
        clarification_applicable=clarification_applicable,
        clarification_appropriate=clarification_appropriate,
        task_success=task_success,
        latency_ms=latency_ms,
        attempt_count=len(attempts),
        output_path=output_path,
        arguments=actual_args,
        error=error,
    )


async def run_cell(
    cell: str,
    provider: str,
    layer: str,
    gateway: LlmGateway,
    cases: list[BenchmarkCaseV2],
    *,
    repeats: int = 3,
    seed: int = 1234,
    preload: bool = True,
    progress: bool = False,
) -> list[CaseRunResult]:
    if preload and hasattr(gateway, "preload"):
        try:
            await gateway.preload(f"bench-{cell}-preload")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - preload failures must not abort the run
            pass

    results: list[CaseRunResult] = []
    for repeat in range(1, repeats + 1):
        ordered = list(cases)
        random.Random(seed + repeat).shuffle(ordered)  # randomized order, recorded via repeat
        for position, case in enumerate(ordered, start=1):
            results.append(
                await _run_one(cell, provider, layer, gateway, case, repeat)
            )
            if progress and position % 20 == 0:
                print(f"  [{cell}] repeat {repeat}/{repeats} {position}/{len(ordered)}")
    return results


async def _run_one(
    cell: str,
    provider: str,
    layer: str,
    gateway: LlmGateway,
    case: BenchmarkCaseV2,
    repeat: int,
) -> CaseRunResult:
    start = time.perf_counter()
    tool_call: ToolCall | None = None
    error: str | None = None
    try:
        tool_call = await gateway.propose_tool_call(
            case.prompt, None, f"bench-{cell}-{repeat}-{case.case_id}"
        )
    except Exception as exc:  # noqa: BLE001 - record the failure, keep the run going
        error = str(exc)
    latency_ms = round((time.perf_counter() - start) * 1000.0, 3)
    attempts = list(getattr(gateway, "last_tool_attempts", []) or [])
    return score_case(
        case,
        tool_call,
        attempts,
        cell=cell,
        provider=provider,
        layer=layer,
        repeat=repeat,
        latency_ms=latency_ms,
        error=error,
    )


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def aggregate_cell(cell: str, results: list[CaseRunResult]) -> dict[str, Any]:
    latencies = [r.latency_ms for r in results if r.error is None]
    retry_latencies = [r.latency_ms for r in results if r.repair_retry_used and r.error is None]
    no_retry_latencies = [
        r.latency_ms for r in results if not r.repair_retry_used and r.error is None
    ]
    clarif = [r for r in results if r.clarification_applicable]
    fallbacks = [r for r in results if r.rule_based_fallback_used]
    retries = [r for r in results if r.repair_retry_used]

    return {
        "cell": cell,
        "n_results": len(results),
        "rates": {
            "task_success": rate_from_flags(r.task_success for r in results).as_dict(),
            "tool_correct": rate_from_flags(r.tool_correct for r in results).as_dict(),
            "args_correct": rate_from_flags(r.args_correct for r in results).as_dict(),
            "json_parse_success": rate_from_flags(
                r.json_parse_success for r in results
            ).as_dict(),
            "schema_validation_success": rate_from_flags(
                r.schema_validation_success for r in results
            ).as_dict(),
            "repair_retry": rate_from_flags(r.repair_retry_used for r in results).as_dict(),
            "rule_based_fallback": rate_from_flags(
                r.rule_based_fallback_used for r in results
            ).as_dict(),
            "clarification_appropriate": rate_from_flags(
                r.clarification_appropriate for r in clarif
            ).as_dict(),
        },
        "diagnostics": {
            "fallback_correctness": rate_from_flags(r.task_success for r in fallbacks).as_dict(),
            "repair_success": rate_from_flags(r.task_success for r in retries).as_dict(),
        },
        "latency_ms": {
            "mean": _mean(latencies),
            **percentiles(latencies, (0.5, 0.95, 0.99)),
            "mean_with_retry": _mean(retry_latencies),
            "mean_without_retry": _mean(no_retry_latencies),
        },
        "per_category": _per_category(results),
        "per_lang": _per_lang(results),
    }


def _per_category(results: list[CaseRunResult]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    by_cat: dict[str, list[CaseRunResult]] = {c: [] for c in CATEGORIES}
    for r in results:
        by_cat[r.category].append(r)
    for category in CATEGORIES:
        rows = by_cat[category]
        out[category] = {
            "task_success": rate_from_flags(r.task_success for r in rows).as_dict(),
            "tool_correct": rate_from_flags(r.tool_correct for r in rows).as_dict(),
            "args_correct": rate_from_flags(r.args_correct for r in rows).as_dict(),
        }
    return out


def _per_lang(results: list[CaseRunResult]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    langs = sorted({r.lang for r in results})
    for lang in langs:
        rows = [r for r in results if r.lang == lang]
        out[lang] = rate_from_flags(r.task_success for r in rows).as_dict()
    return out


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def failure_gallery(results: list[CaseRunResult], limit: int = 8) -> list[dict[str, Any]]:
    failures = [r for r in results if not r.task_success]
    # Deduplicate by case_id, keep the first failing repeat for a compact gallery.
    seen: set[str] = set()
    gallery: list[dict[str, Any]] = []
    for r in failures:
        if r.case_id in seen:
            continue
        seen.add(r.case_id)
        gallery.append(
            {
                "case_id": r.case_id,
                "category": r.category,
                "lang": r.lang,
                "prompt": r.prompt,
                "expected_tool": r.expected_tool,
                "actual_tool": r.actual_tool,
                "arguments": r.arguments,
                "output_path": r.output_path,
                "error": r.error,
            }
        )
        if len(gallery) >= limit:
            break
    return gallery
