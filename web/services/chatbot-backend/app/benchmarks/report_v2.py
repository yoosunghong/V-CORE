"""Render the Phase-2 validation-ablation markdown report (plan section 3.6)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.benchmarks.cases_v2 import CATEGORIES

# Canonical 2x2 cell layout.
PROVIDERS = ("ollama", "llama_cpp")
LAYERS = ("off", "on")
CELL_OF = {
    ("ollama", "off"): "A1",
    ("ollama", "on"): "A2",
    ("llama_cpp", "off"): "B1",
    ("llama_cpp", "on"): "B2",
}
PROVIDER_LABEL = {"ollama": "Ollama", "llama_cpp": "llama.cpp"}


def _pct(rate: dict[str, Any] | None) -> str:
    if not rate or rate.get("total", 0) == 0:
        return "—"
    return (
        f"{rate['rate'] * 100:.1f}% "
        f"[{rate['ci_low'] * 100:.0f}–{rate['ci_high'] * 100:.0f}] "
        f"(n={rate['total']})"
    )


def _pct_plain(rate: dict[str, Any] | None) -> str:
    if not rate or rate.get("total", 0) == 0:
        return "—"
    return f"{rate['rate'] * 100:.1f}%"


def _delta(on: dict[str, Any] | None, off: dict[str, Any] | None) -> str:
    if not on or not off or on.get("total", 0) == 0 or off.get("total", 0) == 0:
        return "—"
    diff = (on["rate"] - off["rate"]) * 100
    sign = "+" if diff >= 0 else ""
    return f"{sign}{diff:.1f} pp"


def render_markdown(run: dict[str, Any]) -> str:
    cells: dict[str, Any] = run["cells"]
    config = run.get("config", {})
    present = set(cells.keys())

    def agg(cell: str) -> dict[str, Any] | None:
        return cells[cell]["aggregate"] if cell in cells else None

    def rate(cell: str, name: str) -> dict[str, Any] | None:
        a = agg(cell)
        return a["rates"][name] if a else None

    lines: list[str] = []
    lines.append("# Phase 2 — Validation-Layer Ablation (v2 benchmark)")
    lines.append("")
    generated = datetime.fromtimestamp(run["generated_at_unix"], tz=timezone.utc)
    lines.append(f"Generated: {generated.isoformat(timespec='seconds')}")
    lines.append("")
    lines.append(
        f"Suite: **{config.get('case_count', '?')} cases** across "
        f"{len(CATEGORIES)} categories · **R={config.get('repeats', '?')} repeats** · "
        f"model `{config.get('model', '?')}`."
    )
    lines.append("")
    lines.append(
        "Cells: **A1/A2** = Ollama validation layer off/on · "
        "**B1/B2** = llama.cpp off/on. *off* = single LLM call, no repair retry, "
        "no rule-based fallback (intrinsic structured-output ability). *on* = full "
        "`propose_tool_call` path (repair retry + deterministic fallback). Rates "
        "carry Wilson 95% CIs."
    )
    lines.append("")

    # 1. Headline 2x2 -------------------------------------------------------
    lines.append("## 1. Headline — Task Success Rate (tool + args correct)")
    lines.append("")
    lines.append("| Provider | Layer OFF | Layer ON |")
    lines.append("|---|---|---|")
    for provider in PROVIDERS:
        off, on = CELL_OF[(provider, "off")], CELL_OF[(provider, "on")]
        if off not in present and on not in present:
            continue
        lines.append(
            f"| {PROVIDER_LABEL[provider]} "
            f"| {_pct(rate(off, 'task_success'))} "
            f"| {_pct(rate(on, 'task_success'))} |"
        )
    lines.append("")

    # 2. Delta validation ---------------------------------------------------
    lines.append("## 2. Validation-layer lift (ON − OFF)")
    lines.append("")
    lines.append("| Provider | Task success Δ | Schema-valid Δ | Tool-correct Δ |")
    lines.append("|---|---|---|---|")
    for provider in PROVIDERS:
        off, on = CELL_OF[(provider, "off")], CELL_OF[(provider, "on")]
        if off not in present or on not in present:
            continue
        lines.append(
            f"| {PROVIDER_LABEL[provider]} "
            f"| {_delta(rate(on, 'task_success'), rate(off, 'task_success'))} "
            f"| {_delta(rate(on, 'schema_validation_success'), rate(off, 'schema_validation_success'))} "
            f"| {_delta(rate(on, 'tool_correct'), rate(off, 'tool_correct'))} |"
        )
    lines.append("")

    # 3. Diagnostic rates per cell -----------------------------------------
    ordered_cells = [c for c in ("A1", "A2", "B1", "B2") if c in present]
    lines.append("## 3. Per-cell diagnostic rates")
    lines.append("")
    header = "| Metric | " + " | ".join(ordered_cells) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(ordered_cells) + 1))
    metric_rows = [
        ("Task success", "task_success"),
        ("Tool correct", "tool_correct"),
        ("Args correct", "args_correct"),
        ("JSON parse", "json_parse_success"),
        ("Schema valid (1st-pass LLM)", "schema_validation_success"),
        ("Repair-retry rate", "repair_retry"),
        ("Rule-based fallback rate", "rule_based_fallback"),
        ("Clarification appropriate", "clarification_appropriate"),
    ]
    for label, name in metric_rows:
        cells_fmt = " | ".join(_pct_plain(rate(c, name)) for c in ordered_cells)
        lines.append(f"| {label} | {cells_fmt} |")
    lines.append("")
    lines.append("Fallback correctness / repair success (of the cases that triggered them):")
    lines.append("")
    lines.append("| Diagnostic | " + " | ".join(ordered_cells) + " |")
    lines.append("|" + "---|" * (len(ordered_cells) + 1))
    for label, key in (("Fallback correctness", "fallback_correctness"), ("Repair success", "repair_success")):
        vals = []
        for c in ordered_cells:
            a = agg(c)
            vals.append(_pct_plain(a["diagnostics"][key]) if a else "—")
        lines.append(f"| {label} | " + " | ".join(vals) + " |")
    lines.append("")

    # 4. Per-category matrix (task success) --------------------------------
    lines.append("## 4. Per-category task success")
    lines.append("")
    lines.append("| Category | " + " | ".join(ordered_cells) + " |")
    lines.append("|" + "---|" * (len(ordered_cells) + 1))
    for category in CATEGORIES:
        vals = []
        for c in ordered_cells:
            a = agg(c)
            vals.append(_pct_plain(a["per_category"][category]["task_success"]) if a else "—")
        lines.append(f"| {category} | " + " | ".join(vals) + " |")
    lines.append("")

    # 5. Latency -----------------------------------------------------------
    lines.append("## 5. Latency (ms)")
    lines.append("")
    lines.append("| Cell | mean | p50 | p95 | p99 | mean w/ retry | mean w/o retry |")
    lines.append("|---|---|---|---|---|---|---|")
    for c in ordered_cells:
        a = agg(c)
        if not a:
            continue
        lat = a["latency_ms"]

        def f(v: Any) -> str:
            return f"{v:.0f}" if isinstance(v, (int, float)) else "—"

        lines.append(
            f"| {c} | {f(lat['mean'])} | {f(lat['p50'])} | {f(lat['p95'])} | "
            f"{f(lat['p99'])} | {f(lat['mean_with_retry'])} | {f(lat['mean_without_retry'])} |"
        )
    lines.append("")

    # 6. Per-language task success -----------------------------------------
    lines.append("## 6. Per-language task success")
    lines.append("")
    langs = sorted({lang for c in ordered_cells if agg(c) for lang in agg(c)["per_lang"]})
    lines.append("| Lang | " + " | ".join(ordered_cells) + " |")
    lines.append("|" + "---|" * (len(ordered_cells) + 1))
    for lang in langs:
        vals = []
        for c in ordered_cells:
            a = agg(c)
            vals.append(_pct_plain(a["per_lang"].get(lang)) if a else "—")
        lines.append(f"| {lang} | " + " | ".join(vals) + " |")
    lines.append("")

    # 7. Failure gallery ---------------------------------------------------
    lines.append("## 7. Failure gallery")
    lines.append("")
    for c in ordered_cells:
        gallery = cells[c].get("gallery", [])
        lines.append(f"### {c}")
        lines.append("")
        if not gallery:
            lines.append("No failures recorded.")
            lines.append("")
            continue
        lines.append("| Case | Lang | Expected | Actual | Path | Prompt |")
        lines.append("|---|---|---|---|---|---|")
        for g in gallery:
            prompt = g["prompt"].replace("|", "\\|")
            if len(prompt) > 70:
                prompt = prompt[:67] + "…"
            lines.append(
                f"| {g['case_id']} | {g['lang']} | {g['expected_tool'] or '—'} "
                f"| {g['actual_tool'] or '—'} | {g['output_path']} | {prompt} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "Raw machine-readable results: `phase2_validation_ablation.json` / "
        "`phase2_validation_ablation.csv` in this directory."
    )
    lines.append("")
    return "\n".join(lines)
