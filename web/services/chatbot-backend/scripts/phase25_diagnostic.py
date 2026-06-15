"""Phase-2.5 pre-SFT semantic diagnostic.

Tests the cheapest Phase-3 lever — a prompt/few-shot change — on the two
layer-immune residual categories (`kpi_acceptance`, `disambiguation`) before any
fine-tuning is commissioned. Reuses the exact Phase-2 scoring/aggregation
(`run_cell` / `aggregate_cell`) so the numbers are directly comparable to
PHASE2B_FULL_RESULTS.md.

For each provider it runs two prompt variants through the *production* layer-ON
path (A2/B2 config): the shipped baseline prompt vs the enriched prompt in
`app/prompts/templates_phase25/`. Per-category Task Success with Wilson 95% CIs.

Example:
    python scripts/phase25_diagnostic.py --providers ollama --repeats 5 \
        --output-dir ../../../docs/benchmark/raw/phase25
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.benchmarks.benchmark_v2 import aggregate_cell, failure_gallery, run_cell  # noqa: E402
from app.benchmarks.cases_v2 import load_cases_dir  # noqa: E402
from app.infrastructure.llm_gateway import LlamaCppLlmGateway, OllamaLlmGateway  # noqa: E402
from app.prompts.templates import PromptTemplateStore  # noqa: E402
from app.tools.router import ToolRouter  # noqa: E402

DEFAULT_CASES = ROOT.parents[2] / "docs" / "benchmark" / "cases" / "v2"
DEFAULT_OUT = ROOT.parents[2] / "docs" / "benchmark" / "raw" / "phase25"
ENRICHED_TEMPLATES = ROOT / "app" / "prompts" / "templates_phase25"

TARGET_CATEGORIES = ("kpi_acceptance", "disambiguation")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Phase-2.5 prompt-lever diagnostic.")
    p.add_argument("--providers", default="ollama", help="Comma list: ollama,llama_cpp")
    p.add_argument("--repeats", type=int, default=5)
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--cases-dir", default=str(DEFAULT_CASES))
    p.add_argument("--output-dir", default=str(DEFAULT_OUT))
    p.add_argument("--ollama-base-url", default=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    p.add_argument("--ollama-model", default=os.getenv("OLLAMA_MODEL", "qwen3.5:2b"))
    p.add_argument("--llama-cpp-base-url", default=os.getenv("LLAMA_CPP_BASE_URL", "http://127.0.0.1:8080"))
    p.add_argument("--llama-cpp-model", default=os.getenv("LLAMA_CPP_MODEL", "qwen3.5:2b"))
    p.add_argument("--timeout-seconds", type=float,
                   default=float(os.getenv("LLM_BENCHMARK_TIMEOUT_SECONDS", "180")))
    return p.parse_args()


def build_gateway(provider: str, prompt_store: PromptTemplateStore, args, tool_router):
    # Production layer-ON config (= A2/B2 in PHASE2B): repair retry + fallback +
    # the two Phase-2-B fixes. Only the prompt store differs across variants.
    common = dict(
        timeout_seconds=args.timeout_seconds,
        structured_retry_count=1,
        enable_rule_based_fallback=True,
        enable_argument_normalization=False,
        enable_decline_retry=True,
        enable_range_validation=True,
        prompt_store=prompt_store,
        tool_router=tool_router,
    )
    if provider == "ollama":
        return OllamaLlmGateway(base_url=args.ollama_base_url, model=args.ollama_model, **common)
    if provider in {"llama_cpp", "llamacpp", "llama.cpp"}:
        return LlamaCppLlmGateway(base_url=args.llama_cpp_base_url, model=args.llama_cpp_model, **common)
    raise ValueError(f"Unsupported provider: {provider}")


def cat_rate(agg: dict[str, Any], category: str) -> dict[str, Any]:
    return agg["per_category"][category]["task_success"]


def fmt(rate: dict[str, Any]) -> str:
    return f"{rate['rate'] * 100:5.1f}% [{rate['ci_low'] * 100:.1f}-{rate['ci_high'] * 100:.1f}]  ({rate['successes']}/{rate['total']})"


async def main() -> None:
    args = parse_args()
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    all_cases = load_cases_dir(args.cases_dir)
    cases = [c for c in all_cases if c.category in TARGET_CATEGORIES]
    print(f"Loaded {len(cases)} target cases ({TARGET_CATEGORIES}); providers={providers} repeats={args.repeats}")

    variants = {
        "baseline": PromptTemplateStore(),  # shipped templates
        "enriched": PromptTemplateStore(template_dir=ENRICHED_TEMPLATES),
    }
    tool_router = ToolRouter()
    out: dict[str, Any] = {"generated_at_unix": time.time(),
                           "config": {"repeats": args.repeats, "seed": args.seed,
                                      "target_categories": list(TARGET_CATEGORIES),
                                      "providers": providers},
                           "results": {}}

    for provider in providers:
        out["results"][provider] = {}
        for variant, store in variants.items():
            cell = f"{provider}_{variant}"
            print(f"== {cell} ==")
            gateway = build_gateway(provider, store, args, tool_router)
            rows = await run_cell(cell, provider, "on", gateway, cases,
                                  repeats=args.repeats, seed=args.seed, preload=True, progress=True)
            agg = aggregate_cell(cell, rows)
            out["results"][provider][variant] = {
                "overall_task_success": agg["rates"]["task_success"],
                "kpi_acceptance": cat_rate(agg, "kpi_acceptance"),
                "disambiguation": cat_rate(agg, "disambiguation"),
                "gallery": failure_gallery(rows, limit=12),
            }
            r = out["results"][provider][variant]
            print(f"   kpi_acceptance: {fmt(r['kpi_acceptance'])}")
            print(f"   disambiguation: {fmt(r['disambiguation'])}")

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    json_path = Path(args.output_dir) / "phase25_prompt_lever.json"
    json_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== SUMMARY (Task Success, layer ON) ===")
    for provider in providers:
        b = out["results"][provider]["baseline"]
        e = out["results"][provider]["enriched"]
        print(f"\n[{provider}]")
        for cat in TARGET_CATEGORIES:
            print(f"  {cat:16s} baseline {fmt(b[cat])}  ->  enriched {fmt(e[cat])}")
    print(f"\nWrote {json_path}")


if __name__ == "__main__":
    asyncio.run(main())
