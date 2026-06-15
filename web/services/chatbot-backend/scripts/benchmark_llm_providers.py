from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.benchmarks.llm_provider_benchmark import (  # noqa: E402
    DEFAULT_BENCHMARK_PROMPTS,
    run_provider_benchmark,
    validate_expected_tools,
    write_benchmark_outputs,
)
from app.infrastructure.llm_gateway import LlamaCppLlmGateway, OllamaLlmGateway  # noqa: E402
from app.tools.router import ToolRouter  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Ollama and llama.cpp on chatbot tool-planning prompts."
    )
    parser.add_argument(
        "--providers",
        default="ollama,llama_cpp",
        help="Comma-separated providers to run: ollama,llama_cpp",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "benchmark_outputs"),
        help="Directory for JSON and CSV benchmark outputs.",
    )
    parser.add_argument(
        "--skip-preload",
        action="store_true",
        help="Skip provider preload/cold-start measurement.",
    )
    parser.add_argument("--ollama-base-url", default=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"))
    parser.add_argument("--ollama-model", default=os.getenv("OLLAMA_MODEL", "qwen3.5:0.8b"))
    parser.add_argument("--llama-cpp-base-url", default=os.getenv("LLAMA_CPP_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--llama-cpp-model", default=os.getenv("LLAMA_CPP_MODEL", "local-llama-cpp"))
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.getenv("LLM_BENCHMARK_TIMEOUT_SECONDS", "120")),
    )
    parser.add_argument(
        "--structured-retry-count",
        type=int,
        default=int(os.getenv("LLM_STRUCTURED_RETRY_COUNT", "1")),
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    validate_expected_tools(DEFAULT_BENCHMARK_PROMPTS)
    providers = [provider.strip() for provider in args.providers.split(",") if provider.strip()]
    tool_router = ToolRouter()
    results: dict[str, dict[str, Any]] = {}

    for provider in providers:
        gateway = build_gateway(provider, args, tool_router)
        results[provider] = await run_provider_benchmark(
            provider,
            gateway,
            DEFAULT_BENCHMARK_PROMPTS,
            preload=not args.skip_preload,
        )

    paths = write_benchmark_outputs(args.output_dir, results)
    print(f"Wrote JSON: {paths['json']}")
    print(f"Wrote CSV: {paths['csv']}")


def build_gateway(provider: str, args: argparse.Namespace, tool_router: ToolRouter):
    if provider == "ollama":
        return OllamaLlmGateway(
            base_url=args.ollama_base_url,
            model=args.ollama_model,
            timeout_seconds=args.timeout_seconds,
            structured_retry_count=args.structured_retry_count,
            tool_router=tool_router,
        )
    if provider in {"llama_cpp", "llamacpp", "llama.cpp"}:
        return LlamaCppLlmGateway(
            base_url=args.llama_cpp_base_url,
            model=args.llama_cpp_model,
            timeout_seconds=args.timeout_seconds,
            structured_retry_count=args.structured_retry_count,
            tool_router=tool_router,
        )
    raise ValueError(f"Unsupported provider: {provider}")


if __name__ == "__main__":
    asyncio.run(main())
