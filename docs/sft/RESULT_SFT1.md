# RESULT — Phase SFT-1: Dataset Creation

**Date:** 2026-06-11 · **Status:** ✅ COMPLETE

## What was produced
A 450-row Domain Tool-Routing SFT dataset (Train 300 / Val 50 / Test 100), built by
deterministic template + slot expansion extending the 133-case v2 benchmark suite.

| Artifact | Path |
|---|---|
| Generator | `docs/sft/scripts/build_sft_dataset.py` |
| Label validator | `docs/sft/scripts/validate_labels.py` |
| Train / Val / Test | `docs/sft/data/{train,val,test}.jsonl` |
| Alias map | `docs/sft/data/alias_map.json` |
| Dataset card | `docs/sft/data/dataset_card.md` |

## Grounding decisions (important)
- **Labels match production, not the prompt's illustrative names.** The task brief used
  placeholder tools (`assign_transport_order`, `move_agv`). The dataset instead targets the
  **9 real tools** in `tools/contracts.py`, and the completion shape is exactly the gateway's
  parse target `{"name", "arguments"}` — so a trained model's output drops straight into the
  live `OllamaLlmGateway`/`ToolRouter` path with no adapter.
- **Decline = production sentinels.** Out-of-scope/status/greeting → `{"name":"none"}`;
  missing-arg/ambiguous/invalid → `{"name":"clarify","arguments":{"message":...}}`. Both are
  already accepted as terminal by the gateway's `_DECLINE_NAMES`, so this satisfies the
  brief's "ask for clarification" intent *and* stays runtime-compatible. (This also bakes in
  the Phase-2-B Fix #1 lesson: the model must be *allowed* to decline rather than coerced.)
- **Over-weighted the two Phase-3 SFT targets** per the Phase-2-B decision: `disambiguation`
  (90 rows total) and `kpi_acceptance` (81). `multi_parameter` was dropped (already 100%).

## Verification
- `validate_labels.py`: **450/450 labels valid** against the live `ToolRouter.validate(check_ranges=True)`.
- Build-time asserts: **zero prompt overlap** across splits (450 unique / 450 total); per-category
  counts exact.
- Language balance ≈ 54% ko / 46% en across all splits.

## Notes / deviations
- Named-area aliases (loading area→1, shipping area→12, warehouse→10 + ko) give the
  "station expression variation" the brief asked for while keeping integer `station_id` labels.
- AGV surface-form variation is cosmetic only (single-AGV tools today → no AGV id arg).

## Next
SFT-2 (LoRA training) — config staged at `docs/sft/data/lora_config.yaml`. Base model is fixed
to the **deployed production base `Qwen/Qwen3.5-2B`** (= Ollama `qwen3.5:2b`, GGUF blob
`sha256-b709d815…`) so the before/after comparison stays valid — SFT-2's purpose is to improve
the production model, not a stand-in. Training runs on host Python (GPU; 4-bit base + adapter
toolchain). SFT-3 eval harness (`scripts/eval_sft.py`) grades the {Base+Full, Base+Minimal,
SFT+Minimal} matrix over the held-out test set. llama.cpp serving commands + model/blob paths
are in `CLAUDE.md` / `AGENT.md`.
