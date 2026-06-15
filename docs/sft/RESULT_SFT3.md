# Phase 3 / SFT-3 — Held-out Evaluation Result

> **Status:** ✅ COMPLETE (2026-06-11) · **Verdict: PASS (all 3 gates met).**
> 3-way matrix over the 100-row held-out `data/test.jsonl`, one scorer
> (`scripts/eval_sft.py`), all three conditions served on the **same** llama.cpp `:8080`
> (build 9559, reasoning-off) for apples-to-apples parity.

## 1. Headline

| Condition | Model | Prompt | **Task Success** |
|---|---|---|---:|
| Base + Full | `qwen3.5:2b` blob | production `tool_planning_system.txt` | **49 %** |
| Base + Minimal | `qwen3.5:2b` blob | 4-line planner prompt | **12 %** |
| **SFT + Minimal** | `vcore-toolrouter.gguf` | 4-line planner prompt | **96 %** |

The SFT model under the **minimal** prompt (96 %) nearly **2×** the base under the full
production prompt (49 %), and **8×** the base under the same minimal prompt (12 %). Routing is
now **in the weights**, not carried by the long hand-tuned prompt.

## 2. Per-category (Task Success %)

| Category | Base+Full | Base+Min | **SFT+Min** | Δ vs Base+Full |
|---|---:|---:|---:|---:|
| disambiguation | 30 | 0 | **95** | +65 |
| inspect_station | 100 | 0 | **100** | 0 |
| invalid_parameter | 0 | 17 | **100** | +100 |
| kpi_acceptance | 50 | 0 | **100** | +50 |
| missing_parameter | 0 | 88 | **100** | +100 |
| move_to_station | 8 | 0 | **83** | +75 |
| negative_control | 100 | 100 | **100** | 0 |
| run_station_task | 100 | 0 | **90** | −10 |
| sim_lifecycle | 75 | 0 | **100** | +25 |
| state_dependent | 100 | 0 | **100** | 0 |
| **Total** | **49** | **12** | **96** | **+47** |

## 3. Verdict vs success gates (plan §3)

1. **SFT+Minimal > Base+Minimal** — 96 % vs 12 %. ✅ (non-overlapping, decisive)
2. **SFT+Minimal ≈ or > Base+Full** — 96 % vs 49 %. ✅ (far exceeds)
3. **KPI-acceptance & Missing-Param not regressed below Base+Full** —
   KPI 50→**100**, Missing-Param 0→**100**. ✅

**All three gates pass.** One minor item: `run_station_task` 100→90 % (1/10 cases) is the only
category below Base+Full; it is not a gate metric and is offset by large gains everywhere else.

## 4. Reading the numbers

- **Why Base+Full is only 49 % here (vs the 94 %/91.7 % production benchmark):** this held-out
  set is intentionally harder — augmented verb/station/alias surface forms with strict exact-arg
  scoring, and includes named-area aliases (`warehouse`→10, `loading area`→1) that require V-CORE
  domain knowledge the stock base lacks under *any* prompt. The categories where Base+Full hits
  0 % (`invalid_parameter`, `missing_parameter`) are decline-discipline cases the base does not
  reliably refuse — SFT learns them (→100 %).
- **Base+Minimal collapse (12 %):** strips the long prompt and the base loses almost all routing
  (disambiguation/move/run/kpi all → 0 %), quantifying how much the production prompt was
  carrying. `missing_parameter` 88 % and `negative_control` 100 % survive because "when unsure,
  decline" is the model's default fallback.
- **SFT+Minimal (96 %):** the 4-line prompt now suffices. The two SFT target categories land at
  disambiguation **95 %** and kpi_acceptance **100 %** (nested `acceptance[]` extraction).

## 5. Repro

Per condition, serve on `:8080` then run the scorer (raw per-row outputs saved to
`data/eval_<model>_<mode>.json`):
```
# base:  -m <qwen3.5:2b blob>      ;  --mode full   and  --mode minimal
# sft:   -m docs/sft/data/vcore-toolrouter.gguf  ;  --mode minimal
docs/sft/scripts/eval_sft.py --endpoint http://127.0.0.1:8080/v1 --model <name> --mode <mode>
```
