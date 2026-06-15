"""Evaluate an integrated path/action model.

Posts the integrated system prompt plus each held-out user request to an
OpenAI-compatible endpoint such as llama.cpp /v1 and grades the returned JSON.

Examples:
    C:/Users/PC/anaconda3/python.exe docs/sft/integrated/scripts/eval_path_action.py \
      --endpoint http://127.0.0.1:8080/v1 --model local-llama-cpp --split test

    C:/Users/PC/anaconda3/python.exe docs/sft/integrated/scripts/eval_path_action.py \
      --provider ollama --endpoint http://127.0.0.1:11434 --model qwen3.5:2b --split test
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[4]
DATA = ROOT / "docs" / "sft" / "integrated" / "data"
PROMPT = ROOT / "docs" / "sft" / "integrated" / "prompts" / "path_action_system.txt"

DECLINE_ROUTES = {"clarify", "no_action"}
ROBOT_ROUTE = "robot_command"


def load_rows(split: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (DATA / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()]


def parse_json(text: str) -> dict[str, Any] | None:
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def normalize(obj: dict[str, Any] | None) -> dict[str, Any]:
    if not obj:
        return {"route": None, "action": None, "arguments": {}}
    route = obj.get("route") or obj.get("intent") or obj.get("path")
    action = obj.get("action") or obj.get("name") or obj.get("tool")
    args = obj.get("arguments") or obj.get("parameters") or {}
    if action in {"none", "no_tool", "noop", "clarify"} and route in {None, ROBOT_ROUTE}:
        route = "clarify" if action == "clarify" else "no_action"
        action = None
    if route != ROBOT_ROUTE:
        action = None
    return {"route": route, "action": action, "arguments": args if isinstance(args, dict) else {}}


def values_equal(expected: Any, got: Any) -> bool:
    if isinstance(expected, float) and isinstance(got, (int, float)):
        return abs(float(expected) - float(got)) < 1e-6
    if isinstance(expected, int) and isinstance(got, (int, float)):
        return int(got) == expected
    return expected == got


def args_match(expected: dict[str, Any], got: dict[str, Any]) -> bool:
    if expected.keys() - got.keys():
        return False
    for key, value in expected.items():
        if key == "acceptance":
            if got.get(key) != value:
                return False
            continue
        if not values_equal(value, got.get(key)):
            return False
    return True


def score(gold: dict[str, Any], pred: dict[str, Any]) -> dict[str, bool]:
    route_ok = gold["route"] == pred["route"]
    action_ok = gold.get("action") == pred.get("action")
    arg_ok = args_match(gold.get("arguments", {}), pred.get("arguments", {}))
    full_ok = route_ok and (gold["route"] != ROBOT_ROUTE or (action_ok and arg_ok))
    false_positive_action = gold["route"] != ROBOT_ROUTE and pred["route"] == ROBOT_ROUTE
    return {
        "route_ok": route_ok,
        "action_ok": action_ok,
        "arg_ok": arg_ok,
        "full_ok": full_ok,
        "false_positive_action": false_positive_action,
    }


def call(provider: str, endpoint: str, model: str, system: str, user: str, timeout: float) -> str:
    if provider == "ollama":
        response = httpx.post(
            f"{endpoint.rstrip('/')}/api/chat",
            json={
                "model": model,
                "stream": False,
                "think": False,
                "format": "json",
                "options": {"temperature": 0, "num_ctx": 2048, "num_predict": 160},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()["message"]["content"]
    response = httpx.post(
        f"{endpoint.rstrip('/')}/chat/completions",
        json={
            "model": model,
            "temperature": 0,
            "max_tokens": 160,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def pct(n: int, d: int) -> float:
    return n / d if d else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="openai", choices=["openai", "ollama"])
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--split", default="test", choices=["train", "val", "test"])
    parser.add_argument("--out", default=None)
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    system = PROMPT.read_text(encoding="utf-8").strip()
    rows = load_rows(args.split)
    results = []
    counts = Counter()
    by_category: dict[str, Counter] = defaultdict(Counter)
    by_route: dict[str, Counter] = defaultdict(Counter)

    for item in rows:
        try:
            raw = call(args.provider, args.endpoint, args.model, system, item["prompt"], args.timeout)
        except Exception as exc:  # noqa: BLE001
            raw = f"ERROR: {exc}"
        pred = normalize(parse_json(raw))
        metrics = score(item["completion"], pred)
        for key, ok in metrics.items():
            counts[key] += int(ok)
            by_category[item["category"]][key] += int(ok)
            by_route[item["completion"]["route"]][key] += int(ok)
        by_category[item["category"]]["n"] += 1
        by_route[item["completion"]["route"]]["n"] += 1
        results.append({**item, "prediction": pred, "raw": raw, **metrics})

    total = len(rows)
    summary = {
        "model": args.model,
        "provider": args.provider,
        "split": args.split,
        "n": total,
        "route_accuracy": pct(counts["route_ok"], total),
        "action_accuracy": pct(counts["action_ok"], total),
        "argument_accuracy": pct(counts["arg_ok"], total),
        "full_decision_accuracy": pct(counts["full_ok"], total),
        "false_positive_action_rate": pct(counts["false_positive_action"], total),
        "by_category": {
            cat: {
                "n": c["n"],
                "route_accuracy": pct(c["route_ok"], c["n"]),
                "full_decision_accuracy": pct(c["full_ok"], c["n"]),
                "false_positive_action_rate": pct(c["false_positive_action"], c["n"]),
            }
            for cat, c in sorted(by_category.items())
        },
        "by_route": {
            route: {
                "n": c["n"],
                "route_accuracy": pct(c["route_ok"], c["n"]),
                "full_decision_accuracy": pct(c["full_ok"], c["n"]),
                "false_positive_action_rate": pct(c["false_positive_action"], c["n"]),
            }
            for route, c in sorted(by_route.items())
        },
        "results": results,
    }

    print(
        f"MODEL={args.model} split={args.split} n={total} "
        f"route={summary['route_accuracy']:.1%} "
        f"full={summary['full_decision_accuracy']:.1%} "
        f"fp_action={summary['false_positive_action_rate']:.1%}"
    )
    for cat, item in summary["by_category"].items():
        print(f"  {cat:22} {item['full_decision_accuracy']:.0%} ({item['n']})")

    out = Path(args.out) if args.out else DATA / f"eval_{args.model}_{args.split}.json".replace("/", "_")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
