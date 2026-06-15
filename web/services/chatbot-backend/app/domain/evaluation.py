from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Qualitative evaluation of a finished simulation run. Thresholds mirror the frontend
# buildAiEvaluation() in web/services/chat-web/src/App.tsx so the LLM narrative and the
# studio/chat AiEvaluationCard stay consistent. Keep the two in sync when tuning.


@dataclass(frozen=True)
class EvalLine:
    text: str
    tone: str  # "good" | "warn" | "bad" | "info"


@dataclass(frozen=True)
class SimulationEvaluation:
    grade: str
    grade_tone: str  # "good" | "warn" | "bad"
    headline: str
    lines: list[EvalLine]

    def to_prompt_block(self) -> str:
        """Structured draft handed to the LLM to rewrite as a flowing narrative."""
        bullets = "\n".join(f"- {line.text}" for line in self.lines)
        return f"등급: {self.grade}\n총평: {self.headline}\n세부 평가:\n{bullets}"

    def to_narrative(self) -> str:
        """Deterministic Korean narrative used when the LLM is unavailable."""
        body = " ".join(line.text for line in self.lines)
        return f"[AI 종합 평가 · {self.grade}] {self.headline} {body}"


def _heatmap_stats(kpis: dict[str, Any]) -> dict[str, Any] | None:
    grid = kpis.get("heatmap_grid")
    if not isinstance(grid, list) or not grid:
        return None
    numeric = [float(value) for value in grid if isinstance(value, (int, float))]
    if not numeric:
        return None
    peak = max(numeric)
    if peak <= 0:
        return None
    res_x_raw = kpis.get("heatmap_res_x")
    res_x = int(res_x_raw) if isinstance(res_x_raw, (int, float)) and res_x_raw else 24
    res_y_raw = kpis.get("heatmap_res_y")
    res_y = int(res_y_raw) if isinstance(res_y_raw, (int, float)) and res_y_raw else round(len(numeric) / res_x)
    traversed_raw = kpis.get("heatmap_traversed_grid")
    if isinstance(traversed_raw, list):
        traversed_indexes = [
            index
            for index, flag in enumerate(traversed_raw[: len(numeric)])
            if isinstance(flag, (bool, int, float)) and bool(flag)
        ]
    else:
        traversed_indexes = [index for index, value in enumerate(numeric) if value > 0.0]
    if not traversed_indexes:
        return None
    traversed_values = [numeric[index] for index in traversed_indexes]
    mean = sum(traversed_values) / len(traversed_values)
    concentration = peak / mean if mean > 0 else 0.0
    hot_fraction = sum(1 for value in traversed_values if value >= peak * 0.6) / len(traversed_values)
    peak_index = numeric.index(peak)
    cx = peak_index % res_x
    cy = peak_index // res_x
    horizontal = "좌측" if cx < res_x / 2 else "우측"
    vertical = "상단" if cy < res_y / 2 else "하단"
    return {
        "concentration": concentration,
        "hot_fraction": hot_fraction,
        "hotspot": f"{vertical} {horizontal}",
    }


def build_simulation_evaluation(kpis: Any, verdict: Any) -> SimulationEvaluation | None:
    """Turn final run KPIs + acceptance verdict into a graded qualitative assessment.

    Returns None when there is nothing to evaluate (no usable KPIs), so callers can skip it.
    """
    if not isinstance(kpis, dict):
        return None

    lines: list[EvalLine] = []
    score = 0
    count = 0

    def rate(good: bool, warn: bool) -> str:
        nonlocal score, count
        count += 1
        score += 2 if good else 1 if warn else 0
        return "good" if good else "warn" if warn else "bad"

    heat = _heatmap_stats(kpis)
    if heat is not None:
        concentrated = heat["concentration"] >= 3.5 and heat["hot_fraction"] <= 0.15
        if concentrated:
            text = (
                f"혼잡 히트맵: 혼잡이 {heat['hotspot']} 구역에 집중되어 국부적 병목 위험이 있습니다 "
                f"(집중도 {heat['concentration']:.1f}배)."
            )
        else:
            text = (
                f"혼잡 히트맵: 혼잡도가 셀 전반에 비교적 고르게 분산되어 있습니다 "
                f"(집중도 {heat['concentration']:.1f}배, 최다 {heat['hotspot']})."
            )
        lines.append(EvalLine(text=text, tone="warn" if concentrated else "good"))

    bottleneck = kpis.get("bottleneck_rate")
    if isinstance(bottleneck, (int, float)):
        tone = rate(bottleneck <= 30, bottleneck <= 50)
        note = {
            "good": "혼잡이 일부 구역에 한정되어 병목 위험이 낮습니다.",
            "warn": "병목 구역이 늘어 흐름 저하가 우려됩니다.",
            "bad": "병목이 셀 전반으로 확산되어 AGV 대수·경로 재조정이 필요합니다.",
        }[tone]
        lines.append(EvalLine(text=f"병목률 {bottleneck:.1f}% — {note}", tone=tone))

    throughput = kpis.get("throughput")
    if isinstance(throughput, (int, float)):
        tone = rate(throughput >= 60, throughput >= 40)
        note = {
            "good": "목표 처리량을 충분히 달성했습니다.",
            "warn": "목표에 근접하나 개선 여지가 있습니다.",
            "bad": "목표를 크게 밑돌아 라인 효율 점검이 필요합니다.",
        }[tone]
        lines.append(EvalLine(text=f"처리량 {throughput:.1f}/h — {note}", tone=tone))

    avg_wait = kpis.get("avg_wait_time")
    if isinstance(avg_wait, (int, float)):
        tone = rate(avg_wait <= 10, avg_wait <= 20)
        note = {
            "good": "교차로 대기가 짧아 흐름이 원활합니다.",
            "warn": "대기시간이 다소 길어 일부 정체가 보입니다.",
            "bad": "대기시간이 길어 병목이 발생하고 있습니다.",
        }[tone]
        lines.append(EvalLine(text=f"평균 대기시간 {avg_wait:.1f}s — {note}", tone=tone))

    collision = kpis.get("collision_risk")
    if isinstance(collision, (int, float)):
        tone = rate(collision <= 0.5, collision <= 1.5)
        note = {
            "good": "충돌 위험이 낮아 안전성이 확보되었습니다.",
            "warn": "간헐적 충돌 위험이 관측됩니다.",
            "bad": "충돌 위험이 높아 경로·우선순위 정책 재검토가 필요합니다.",
        }[tone]
        lines.append(EvalLine(text=f"충돌 위험도 {collision:.2f}/h — {note}", tone=tone))

    uptime = kpis.get("uptime")
    if isinstance(uptime, (int, float)):
        tone = rate(uptime >= 0.95, uptime >= 0.85)
        note = {
            "good": "설비 가동률이 우수합니다.",
            "warn": "양호하나 유휴 구간이 존재합니다.",
            "bad": "가동률이 낮아 유휴·정지 원인 분석이 필요합니다.",
        }[tone]
        lines.append(EvalLine(text=f"가동률 {uptime * 100:.0f}% — {note}", tone=tone))

    if not lines:
        return None

    ratio = score / (count * 2) if count > 0 else 0.5
    if ratio >= 0.8:
        grade, grade_tone = "A · 우수", "good"
    elif ratio >= 0.55:
        grade, grade_tone = "B · 양호", "warn"
    else:
        grade, grade_tone = "C · 주의", "bad"

    verdict_dict = verdict if isinstance(verdict, dict) else None
    if verdict_dict is not None:
        headline = (
            "수용 기준을 통과했으며 핵심 KPI가 안정적으로 유지되었습니다."
            if verdict_dict.get("passed")
            else "수용 기준 미달 항목이 있어 아래 지표를 우선 개선해야 합니다."
        )
    elif grade_tone == "good":
        headline = "전반적으로 안정적인 운영 성능을 보였습니다."
    elif grade_tone == "warn":
        headline = "운영은 가능하나 일부 지표에서 개선이 필요합니다."
    else:
        headline = "여러 지표에서 위험이 감지되어 정책 재검토를 권장합니다."

    return SimulationEvaluation(grade=grade, grade_tone=grade_tone, headline=headline, lines=lines)


# A/B comparison of two finished runs. Closes the loop on the project's "pre-verification of
# operational strategies" thesis: run A vs run B, decided on the same KPI set the single-run
# evaluation above grades, with an acceptance-verdict override when exactly one run passed.


@dataclass(frozen=True)
class ComparedRun:
    label: str
    kpis: dict[str, Any]
    verdict: dict[str, Any] | None = None


@dataclass(frozen=True)
class RunComparison:
    headline: str
    winner_label: str | None
    lines: list[EvalLine]

    def to_narrative(self) -> str:
        body = " ".join(line.text for line in self.lines)
        return f"[실행 비교] {self.headline} {body}"


# (kpi key, label, higher_is_better, value formatter). Mirrors the KPI directions used by
# build_simulation_evaluation so a metric "win" here agrees with the single-run grade.
_COMPARE_METRICS: tuple[tuple[str, str, bool, Any], ...] = (
    ("throughput", "처리량", True, lambda v: f"{v:.1f}/h"),
    ("avg_wait_time", "평균 대기시간", False, lambda v: f"{v:.1f}s"),
    ("bottleneck_rate", "병목률", False, lambda v: f"{v:.1f}%"),
    ("collision_risk", "충돌 위험도", False, lambda v: f"{v:.2f} 건/h"),
    ("uptime", "가동률", True, lambda v: f"{v * 100:.0f}%"),
)


def _verdict_passed(verdict: Any) -> bool | None:
    """True/False only when the run carried real acceptance criteria; None otherwise."""
    if not isinstance(verdict, dict):
        return None
    passed = verdict.get("passed")
    if not isinstance(passed, bool):
        return None
    if not (verdict.get("passed_labels") or verdict.get("failed_labels")):
        return None
    return passed


def build_run_comparison(run_a: ComparedRun, run_b: ComparedRun) -> RunComparison | None:
    """Compare two runs' KPIs into a graded verdict. None when they share no usable KPI."""
    if not isinstance(run_a.kpis, dict) or not isinstance(run_b.kpis, dict):
        return None

    lines: list[EvalLine] = []
    wins_a = 0
    wins_b = 0
    for key, label, higher_is_better, fmt in _COMPARE_METRICS:
        a = run_a.kpis.get(key)
        b = run_b.kpis.get(key)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            continue
        if a == b:
            verdict_text = "동일"
        else:
            a_better = a > b if higher_is_better else a < b
            if a_better:
                wins_a += 1
                verdict_text = f"{run_a.label} 우세"
            else:
                wins_b += 1
                verdict_text = f"{run_b.label} 우세"
        lines.append(
            EvalLine(
                text=f"{label}: {run_a.label} {fmt(a)} vs {run_b.label} {fmt(b)} → {verdict_text}",
                tone="info",
            )
        )

    if not lines:
        return None

    passed_a = _verdict_passed(run_a.verdict)
    passed_b = _verdict_passed(run_b.verdict)
    total = wins_a + wins_b
    if passed_a is not None and passed_b is not None and passed_a != passed_b:
        winner_label = run_a.label if passed_a else run_b.label
        headline = f"{winner_label}만 수용 기준을 통과해 종합적으로 더 우수합니다."
    elif wins_a > wins_b:
        winner_label = run_a.label
        headline = f"{winner_label}이(가) {wins_a}/{total} 지표에서 앞서 더 우수합니다."
    elif wins_b > wins_a:
        winner_label = run_b.label
        headline = f"{winner_label}이(가) {wins_b}/{total} 지표에서 앞서 더 우수합니다."
    else:
        winner_label = None
        headline = "두 실행이 박빙입니다 — 지표별 트레이드오프가 있어 운영 목표에 따라 선택하세요."

    for run, passed in ((run_a, passed_a), (run_b, passed_b)):
        if passed is not None:
            lines.append(
                EvalLine(
                    text=f"{run.label} 수용 기준: {'통과' if passed else '미달'}",
                    tone="good" if passed else "bad",
                )
            )

    return RunComparison(headline=headline, winner_label=winner_label, lines=lines)
