"""Benchmark v2 case model, JSONL I/O, argument-level scoring, and Wilson CIs.

This is the W1/W2/W3 fix layer for the Phase-2 plan
(docs/benchmark/BENCHMARK_PHASE2_PHASE3_PLAN.md): cases carry structured
expectations so arguments are graded (not just tool names), every reported rate
ships with a Wilson 95% confidence interval, and the suite lives as static,
version-controlled JSONL so runs are reproducible.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

# The 12 categories of the v2 suite (plan section 2.3). Kept as a constant so the
# generator, runner, and report all agree on the canonical set and ordering.
CATEGORIES: tuple[str, ...] = (
    "positive_invocation",
    "negative_control",
    "ambiguous",
    "parameter_extraction",
    "multi_parameter",
    "missing_parameter",
    "long_request",
    "kpi_acceptance",
    "invalid_parameter",
    "disambiguation",
    "sequential",
    "state_dependent",
)

ARG_MATCH_MODES = frozenset({"exact", "subset", "ignore"})


@dataclass(frozen=True)
class BenchmarkCaseV2:
    case_id: str
    category: str
    lang: str  # "en" | "ko" | "mixed"
    prompt: str
    expected_tool: str | None  # None = expect no tool (negative control)
    expected_args: dict[str, Any] | None = None
    arg_match: str = "subset"  # "exact" | "subset" | "ignore"
    accept_alternatives: tuple[str, ...] = ()
    expect_clarification: bool = False
    difficulty: str = "normal"  # "easy" | "normal" | "hard"
    notes: str = ""

    def __post_init__(self) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"{self.case_id}: unknown category {self.category!r}")
        if self.arg_match not in ARG_MATCH_MODES:
            raise ValueError(f"{self.case_id}: unknown arg_match {self.arg_match!r}")

    def to_jsonl_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["accept_alternatives"] = list(self.accept_alternatives)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BenchmarkCaseV2":
        return cls(
            case_id=data["case_id"],
            category=data["category"],
            lang=data["lang"],
            prompt=data["prompt"],
            expected_tool=data.get("expected_tool"),
            expected_args=data.get("expected_args"),
            arg_match=data.get("arg_match", "subset"),
            accept_alternatives=tuple(data.get("accept_alternatives", ()) or ()),
            expect_clarification=bool(data.get("expect_clarification", False)),
            difficulty=data.get("difficulty", "normal"),
            notes=data.get("notes", ""),
        )


def write_cases_jsonl(path: str | Path, cases: Iterable[BenchmarkCaseV2]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with target.open("w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            handle.write(json.dumps(case.to_jsonl_dict(), ensure_ascii=False))
            handle.write("\n")
            count += 1
    return count


def load_cases_jsonl(path: str | Path) -> list[BenchmarkCaseV2]:
    cases: list[BenchmarkCaseV2] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        cases.append(BenchmarkCaseV2.from_dict(json.loads(line)))
    return cases


def load_cases_dir(directory: str | Path) -> list[BenchmarkCaseV2]:
    cases: list[BenchmarkCaseV2] = []
    seen: set[str] = set()
    for jsonl in sorted(Path(directory).glob("*.jsonl")):
        for case in load_cases_jsonl(jsonl):
            if case.case_id in seen:
                raise ValueError(f"duplicate case_id across suite: {case.case_id}")
            seen.add(case.case_id)
            cases.append(case)
    return cases


# --------------------------------------------------------------------------- #
# Argument-level scoring (the W3 fix)
# --------------------------------------------------------------------------- #


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def values_match(expected: Any, actual: Any) -> bool:
    """Compare one expected vs actual argument value.

    Numbers compare across int/float and numeric strings ("3" == 3) so a model
    that emits a stringified number is not penalised at the value level. Lists
    use order-independent subset semantics; dicts use subset semantics — this is
    what the nested ``acceptance`` array needs (plan category 8).
    """
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return False
        return all(
            key in actual and values_match(sub, actual[key])
            for key, sub in expected.items()
        )
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return False
        return all(
            any(values_match(item, candidate) for candidate in actual)
            for item in expected
        )
    exp_num, act_num = _numeric(expected), _numeric(actual)
    if exp_num is not None and act_num is not None:
        return math.isclose(exp_num, act_num, rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() == actual.strip().lower()
    return expected == actual


def args_match(
    expected_args: dict[str, Any] | None,
    actual_args: dict[str, Any] | None,
    mode: str,
) -> bool:
    """Grade the argument dict per ``arg_match`` mode.

    - ``ignore``: arguments are not scored (True).
    - ``subset``: every expected key/value must be present & correct; extra
      actual args are allowed (defaults don't penalise).
    - ``exact``: key sets must match exactly and every value must be correct.
    """
    if mode == "ignore":
        return True
    expected = expected_args or {}
    actual = actual_args or {}
    if mode == "exact" and set(expected) != set(actual):
        return False
    return all(
        key in actual and values_match(value, actual[key])
        for key, value in expected.items()
    )


# --------------------------------------------------------------------------- #
# Wilson score interval (the W1/W2 fix)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Rate:
    successes: int
    total: int
    rate: float
    ci_low: float
    ci_high: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def wilson_rate(successes: int, total: int, z: float = 1.96) -> Rate:
    if total <= 0:
        return Rate(0, 0, 0.0, 0.0, 0.0)
    phat = successes / total
    denom = 1.0 + z * z / total
    center = (phat + z * z / (2.0 * total)) / denom
    margin = (z / denom) * math.sqrt(
        phat * (1.0 - phat) / total + z * z / (4.0 * total * total)
    )
    return Rate(
        successes=successes,
        total=total,
        rate=phat,
        ci_low=max(0.0, center - margin),
        ci_high=min(1.0, center + margin),
    )


def rate_from_flags(flags: Iterable[bool]) -> Rate:
    items = list(flags)
    return wilson_rate(sum(1 for flag in items if flag), len(items))


def percentiles(values: list[float], points: Iterable[float]) -> dict[str, float | None]:
    if not values:
        return {f"p{int(p * 100)}": None for p in points}
    ordered = sorted(values)
    out: dict[str, float | None] = {}
    for p in points:
        idx = max(0, math.ceil(p * len(ordered)) - 1)
        out[f"p{int(p * 100)}"] = ordered[idx]
    return out


def iter_categories(cases: Iterable[BenchmarkCaseV2]) -> Iterator[tuple[str, list[BenchmarkCaseV2]]]:
    grouped: dict[str, list[BenchmarkCaseV2]] = {category: [] for category in CATEGORIES}
    for case in cases:
        grouped[case.category].append(case)
    for category in CATEGORIES:
        yield category, grouped[category]
