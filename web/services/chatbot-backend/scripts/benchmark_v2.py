"""Phase-2 v2 ablation runner.

Runs the 2x2 validation-layer ablation (Ollama/llama.cpp x layer off/on) over the
static v2 JSONL suite, with R repeats and Wilson CIs, then writes JSON + CSV +
the markdown report (`phase2_validation_ablation.*`).

Examples
--------
Ollama-only ablation (A1 + A2), 3 repeats:
    python scripts/benchmark_v2.py --providers ollama --repeats 3 \
        --ollama-base-url http://127.0.0.1:11434 --ollama-model qwen3.5:2b \
        --output-dir ../../../docs/benchmark/raw

Quick smoke (2 cases/category, 1 repeat):
    python scripts/benchmark_v2.py --providers ollama --repeats 1 --limit-per-category 2
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.benchmarks.benchmark_v2 import (  # noqa: E402
    CaseRunResult,
    aggregate_cell,
    failure_gallery,
    run_cell,
)
from app.benchmarks.cases_v2 import CATEGORIES, BenchmarkCaseV2, load_cases_dir  # noqa: E402
from app.benchmarks.report_v2 import CELL_OF, render_markdown  # noqa: E402
from app.infrastructure.llm_gateway import LlamaCppLlmGateway, OllamaLlmGateway  # noqa: E402
from app.tools.router import ToolRouter  # noqa: E402

DEFAULT_CASES = ROOT.parents[2] / "docs" / "benchmark" / "cases" / "v2"
DEFAULT_OUT = ROOT.parents[2] / "docs" / "benchmark" / "raw"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase-2 validation-layer ablation runner.")
    parser.add_argument("--providers", default="ollama", help="Comma list: ollama,llama_cpp")
    parser.add_argument("--layers", default="off,on", help="Comma list: off,on")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument("--limit-per-category", type=int, default=0, help="0 = all cases")
    parser.add_argument("--cases-dir", default=str(DEFAULT_CASES))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--enable-normalization", action="store_true",
                        help="Add the argument-normalization component to the layer-ON cells.")
    parser.add_argument("--skip-preload", action="store_true")
    parser.add_argument("--ollama-base-url", default=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--ollama-model", default=os.getenv("OLLAMA_MODEL", "qwen3.5:2b"))
    parser.add_argument("--llama-cpp-base-url", default=os.getenv("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument("--llama-cpp-model", default=os.getenv("LLAMA_CPP_MODEL", "qwen3.5:2b"))
    parser.add_argument("--timeout-seconds", type=float,
                        default=float(os.getenv("LLM_BENCHMARK_TIMEOUT_SECONDS", "180")))
    return parser.parse_args()


def sample_cases(cases: list[BenchmarkCaseV2], limit_per_category: int) -> list[BenchmarkCaseV2]:
    if limit_per_category <= 0:
        return cases
    kept: list[BenchmarkCaseV2] = []
    counts: dict[str, int] = {c: 0 for c in CATEGORIES}
    for case in cases:
        if counts[case.category] < limit_per_category:
            kept.append(case)
            counts[case.category] += 1
    return kept


def build_gateway(
    provider: str,
    layer: str,
    args: argparse.Namespace,
    tool_router: ToolRouter,
):
    layer_on = layer == "on"
    common = dict(
        timeout_seconds=args.timeout_seconds,
        # Layer OFF = intrinsic: no repair retry, no fallback. ON = production stack.
        structured_retry_count=1 if layer_on else 0,
        enable_rule_based_fallback=layer_on,
        enable_argument_normalization=layer_on and args.enable_normalization,
        # Phase-2-B fixes ride on the ON cells only (A2/B2); OFF cells stay the
        # Phase-2-A intrinsic baseline so the ablation contrast is clean.
        enable_decline_retry=layer_on,
        enable_range_validation=layer_on,
        tool_router=tool_router,
    )
    if provider == "ollama":
        return OllamaLlmGateway(base_url=args.ollama_base_url, model=args.ollama_model, **common)
    if provider in {"llama_cpp", "llamacpp", "llama.cpp"}:
        return LlamaCppLlmGateway(
            base_url=args.llama_cpp_base_url, model=args.llama_cpp_model, **common
        )
    raise ValueError(f"Unsupported provider: {provider}")


def write_outputs(output_dir: Path, run: dict[str, Any], all_rows: list[CaseRunResult]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "phase2_validation_ablation.json"
    csv_path = output_dir / "phase2_validation_ablation.csv"
    md_path = output_dir / "phase2_validation_ablation.md"

    json_path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")

    if all_rows:
        fieldnames = list(asdict(all_rows[0]).keys())
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in all_rows:
                record = asdict(row)
                record["arguments"] = json.dumps(record["arguments"], ensure_ascii=False)
                writer.writerow(record)

    md_path.write_text(render_markdown(run), encoding="utf-8")
    return {"json": str(json_path), "csv": str(csv_path), "md": str(md_path)}


async def main() -> None:
    args = parse_args()
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    layers = [layer.strip() for layer in args.layers.split(",") if layer.strip()]
    cases = sample_cases(load_cases_dir(args.cases_dir), args.limit_per_category)
    print(f"Loaded {len(cases)} cases; providers={providers} layers={layers} repeats={args.repeats}")

    tool_router = ToolRouter()
    cells: dict[str, Any] = {}
    all_rows: list[CaseRunResult] = []

    for provider in providers:
        for layer in layers:
            cell = CELL_OF.get((provider, layer), f"{provider}_{layer}")
            print(f"== Running cell {cell} ({provider}, layer {layer}) ==")
            gateway = build_gateway(provider, layer, args, tool_router)
            results = await run_cell(
                cell, provider, layer, gateway, cases,
                repeats=args.repeats, seed=args.seed,
                preload=not args.skip_preload, progress=True,
            )
            all_rows.extend(results)
            cells[cell] = {
                "provider": provider,
                "layer": layer,
                "aggregate": aggregate_cell(cell, results),
                "gallery": failure_gallery(results),
            }
            ts = cells[cell]["aggregate"]["rates"]["task_success"]
            print(f"   {cell} task_success = {ts['rate'] * 100:.1f}% (n={ts['total']})")

    run = {
        "generated_at_unix": time.time(),
        "config": {
            "case_count": len(cases),
            "repeats": args.repeats,
            "seed": args.seed,
            "model": args.ollama_model if "ollama" in providers else args.llama_cpp_model,
            "providers": providers,
            "layers": layers,
            "enable_normalization": args.enable_normalization,
        },
        "cells": cells,
    }

    paths = write_outputs(Path(args.output_dir), run, all_rows)
    print(f"Wrote report: {paths['md']}")
    print(f"Wrote JSON:   {paths['json']}")
    print(f"Wrote CSV:    {paths['csv']}")


if __name__ == "__main__":
    asyncio.run(main())
