"""End-to-end test of the adapter-toggle gateway: ONE llama.cpp base + routing LoRA,
toggled per request. Proves a single in-VRAM model serves all three functions:

  - routing  (propose_tool_call) -> adapter scale 1.0  -> graded vs test.jsonl labels
  - report   (generate_report)   -> adapter scale 0.0  -> defect scan (dup / CJK leak)
  - chat     (generate_chat)     -> adapter scale 0.0  -> defect scan

Run the backend container code path via the real RoutingSplitLlmGateway built by
AppContainer with LLM_PROVIDER=adapter_toggle, pointed at the single llama.cpp endpoint.

Usage (from web/services/chatbot-backend), with the base+adapter server on :8090:
  C:/Users/PC/anaconda3/python.exe ../../../docs/sft/integrated/scripts/test_adapter_toggle.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time

sys.path.insert(0, ".")

from app.domain.models import Station  # noqa: E402
from app.infrastructure.config import Settings  # noqa: E402
from app.infrastructure.container import AppContainer  # noqa: E402

# Reuse the report/chat fixtures from the comparison harness.
sys.path.insert(0, "../../../docs/sft/integrated/scripts")
from compare_chat_report import CHAT_CASES, REPORT_CASES  # noqa: E402

ENDPOINT = "http://localhost:8090"
TEST_JSONL = "../../../docs/sft/integrated/data/test.jsonl"


def _canon(v):
    """Deep-canonicalize an argument value: numbers -> float, drop cosmetic 'label'
    keys, numeric strings -> number. So 70 == 70.0 and an extra human-readable label on
    an acceptance criterion is not counted as a routing error."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if s.lstrip("-").isdigit():
            return float(s)
        try:
            return float(s)
        except ValueError:
            return s
    if isinstance(v, list):
        return [_canon(x) for x in v]
    if isinstance(v, dict):
        return {k: _canon(x) for k, x in sorted(v.items()) if k != "label"}
    return v


def _norm(d: dict) -> tuple:
    """Canonicalize a route/action decision for comparison."""
    return (d.get("route"), d.get("action"), json.dumps(_canon(d.get("arguments") or {}), sort_keys=True))


def cjk_leak(t: str) -> list[str]:
    return [w for w in ["您好", "你好", "谢谢", "请问", "正在", "已经"] if w in t]


def dup_block(t: str) -> bool:
    lines = [l.strip() for l in t.split("\n") if len(l.strip()) > 15]
    return len(lines) != len(set(lines))


async def grade_routing(gw) -> dict:
    """Routing accuracy through propose_tool_call (adapter on). Compares the resulting
    ToolCall to the labelled robot_command rows; non-robot rows are checked as 'no tool'."""
    rows = [json.loads(l) for l in open(TEST_JSONL, encoding="utf-8")]
    ok = 0
    n = 0
    mismatches = []
    for r in rows:
        comp = r["completion"]
        n += 1
        tc = await gw.propose_tool_call(r["prompt"], None, "corr-route")
        # move_to_station is internal-only by system design: the gateway returns None and
        # the orchestrator's ambiguous-command path handles the user "move" request. So a
        # None here for a move_to_station label is the intended behavior, not an error.
        if comp.get("action") == "move_to_station":
            if tc is None or tc.name.value == "move_to_station":
                ok += 1
            else:
                mismatches.append((r["prompt"][:40], "move(internal)->None", tc.name.value))
        elif comp["route"] == "robot_command" and comp.get("action"):
            # Expect a tool call whose name == action and args match.
            got = None
            if tc is not None:
                got = {"route": "robot_command", "action": tc.name.value, "arguments": tc.arguments}
            if got and _norm(got) == _norm(comp):
                ok += 1
            else:
                mismatches.append((r["prompt"][:40], _norm(comp), _norm(got) if got else None))
        else:
            # Non-actionable route: a correct router declines (no internal-only/invalid tool).
            # move_to_station is internal-only, so robot_command+move can legitimately be None too.
            if tc is None or comp["action"] == "move_to_station":
                ok += 1
            else:
                mismatches.append((r["prompt"][:40], comp["route"], tc.name.value if tc else None))
    return {"correct": ok, "total": n, "accuracy": round(ok / n, 4), "mismatches": mismatches[:12]}


async def run_reports(gw) -> list:
    out = []
    for c in REPORT_CASES:
        t0 = time.perf_counter()
        text = await gw.generate_report(c["event"], c["command"], "corr-rep", evaluation=c["evaluation"])
        out.append({
            "case": c["name"], "latency_s": round(time.perf_counter() - t0, 2),
            "dup": dup_block(text), "cjk": cjk_leak(text), "text": text,
        })
    return out


async def run_chats(gw) -> list:
    out = []
    for c in CHAT_CASES:
        t0 = time.perf_counter()
        text = await gw.generate_chat_response(c["message"], c["history"], "corr-chat")
        out.append({
            "case": c["name"], "latency_s": round(time.perf_counter() - t0, 2),
            "dup": dup_block(text), "cjk": cjk_leak(text), "text": text,
        })
    return out


async def main():
    settings = Settings(
        llm_provider="adapter_toggle",
        llama_cpp_base_url=ENDPOINT,
        llama_cpp_model="vcore-base",
        llama_cpp_num_ctx=8192,
        llama_cpp_timeout_seconds=120,
        llama_cpp_report_num_predict=512,
    )
    gw = AppContainer(settings=settings).llm
    print("gateway:", type(gw).__name__,
          "| routing scale", gw._routing._adapter_scale,
          "| general scale", gw._general._adapter_scale)

    print("\n== ROUTING (adapter scale 1.0) ==")
    routing = await grade_routing(gw)
    print(f"  accuracy: {routing['accuracy']*100:.1f}%  ({routing['correct']}/{routing['total']})")
    for m in routing["mismatches"]:
        print("   MISS", m)

    print("\n== REPORTS (adapter scale 0.0) ==")
    reports = await run_reports(gw)
    for r in reports:
        flags = []
        if r["dup"]:
            flags.append("DUP")
        if r["cjk"]:
            flags.append("CJK:" + ",".join(r["cjk"]))
        print(f"  {r['case']}: {r['latency_s']}s {' '.join(flags) if flags else 'clean'}")

    print("\n== CHAT (adapter scale 0.0) ==")
    chats = await run_chats(gw)
    for c in chats:
        flags = []
        if c["dup"]:
            flags.append("DUP")
        if c["cjk"]:
            flags.append("CJK:" + ",".join(c["cjk"]))
        print(f"  {c['case']}: {c['latency_s']}s {' '.join(flags) if flags else 'clean'}")

    out = {"routing": routing, "reports": reports, "chats": chats}
    path = "../../../docs/sft/integrated/data/adapter_toggle_test.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\nwrote", path)

    report_defects = sum(r["dup"] or bool(r["cjk"]) for r in reports)
    chat_defects = sum(c["dup"] or bool(c["cjk"]) for c in chats)
    print(f"\nSUMMARY: routing {routing['accuracy']*100:.1f}% | "
          f"report defects {report_defects}/{len(reports)} | chat defects {chat_defects}/{len(chats)}")


if __name__ == "__main__":
    asyncio.run(main())
