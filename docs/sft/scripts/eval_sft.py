"""Phase 3 / SFT-3 — held-out eval over docs/sft/data/test.jsonl.

Scores the 3-way matrix {Base+Full, Base+Minimal, SFT+Minimal} with one scorer so
the comparison is apples-to-apples. Posts to an OpenAI-compatible /chat endpoint
(Ollama :11434 or llama.cpp :8080) and grades the parsed tool JSON against the gold
``completion``.

Grading
  - real-tool gold: success = tool name matches AND args match (exact|subset by category).
  - decline gold (name in {none, clarify}): success = model emits no actionable tool
    (decline sentinel or empty/`none`). For `clarify` we also accept any decline.

Run (after a model is served), e.g.:
  C:/Users/PC/anaconda3/python.exe docs/sft/scripts/eval_sft.py \
      --endpoint http://localhost:8080/v1 --model vcore-toolrouter --mode minimal
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "web" / "services" / "chatbot-backend"
DATA = Path(__file__).resolve().parents[1] / "data"
PROMPTS = BACKEND / "app" / "prompts" / "templates"

DECLINE = {"none", "no_tool", "no-tool", "noop", "null", "clarify", "clarification", ""}
# arg_match policy per category (mirrors the v2 suite)
EXACT = {"move_to_station", "inspect_station", "disambiguation"}
IGNORE_ARGS = {"sim_lifecycle", "state_dependent"}

MINIMAL_PROMPT = (
    "You are the V-CORE tool planner.\n"
    "Given a user command, select exactly one tool and produce valid JSON arguments.\n"
    "Do not explain. Do not invent missing IDs. If required information is missing,\n"
    "return the clarify tool instead of guessing.\n"
    'Output JSON only: {"name": <tool>, "arguments": {...}}.'
)


def full_prompt() -> str:
    return (PROMPTS / "tool_planning_system.txt").read_text(encoding="utf-8")


def parse_tool(text: str) -> dict | None:
    """Extract the first {"name":...} JSON object from a raw model response."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) and "name" in obj else None


def args_match(category: str, gold: dict, got: dict) -> bool:
    if category in IGNORE_ARGS:
        return True
    if category in EXACT:
        return gold == got
    # subset: every gold key/value present in got (handles acceptance[] supersets)
    return all(got.get(k) == v for k, v in gold.items())


def score_row(row: dict, pred: dict | None) -> bool:
    gold = row["completion"]
    gname = gold["name"]
    pname = (pred or {}).get("name", "") if pred else ""
    if gname in DECLINE:
        return pname in DECLINE
    if pred is None or pname != gname:
        return False
    return args_match(row["category"], gold.get("arguments", {}), pred.get("arguments", {}))


def call(endpoint: str, model: str, system: str, user: str) -> str:
    r = httpx.post(
        f"{endpoint.rstrip('/')}/chat/completions",
        json={"model": model, "temperature": 0,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=60.0,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--mode", choices=["full", "minimal"], required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    system = full_prompt() if a.mode == "full" else MINIMAL_PROMPT
    rows = [json.loads(l) for l in (DATA / "test.jsonl").read_text(encoding="utf-8").splitlines()]

    by_cat: dict[str, list[bool]] = {}
    results = []
    for row in rows:
        try:
            raw = call(a.endpoint, a.model, system, row["prompt"])
        except Exception as exc:  # noqa: BLE001
            print(f"call failed: {exc}", file=sys.stderr)
            raw = ""
        ok = score_row(row, parse_tool(raw))
        by_cat.setdefault(row["category"], []).append(ok)
        results.append({**row, "raw": raw, "correct": ok})

    total = [ok for oks in by_cat.values() for ok in oks]
    print(f"\nMODEL={a.model}  MODE={a.mode}  Task Success = {sum(total)}/{len(total)} = {sum(total)/len(total):.1%}\n")
    for cat in sorted(by_cat):
        oks = by_cat[cat]
        print(f"  {cat:18} {sum(oks):>3}/{len(oks):<3} {sum(oks)/len(oks):.0%}")

    out = Path(a.out) if a.out else DATA / f"eval_{a.model}_{a.mode}.json".replace("/", "_")
    out.write_text(json.dumps({"model": a.model, "mode": a.mode,
                               "task_success": sum(total) / len(total),
                               "by_category": {c: sum(v) / len(v) for c, v in by_cat.items()},
                               "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
