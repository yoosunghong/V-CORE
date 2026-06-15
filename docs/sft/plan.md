# Phase 3 — Domain Tool-Routing SFT (LoRA) Plan

> **Status:** SFT-1 in progress · **Owner:** VCORE LLM track · **Created:** 2026-06-11
> **Parent decision:** Phase 2-B PASS → Phase 3 LoRA SFT = *conditional GO*. See
> `docs/benchmark/PHASE2B_FULL_RESULTS.md` and memory `phase2b-full-results-serving-resolved`.

## 0. Framing (why this is worth doing even though prod is already good)

Production already hits **KPI Acceptance 94%** and **Disambiguation 91.7%** (llama.cpp,
reasoning-off) through prompt + serving optimization. So SFT is **not** justified as an
operational-performance fix. The justification is **portfolio capability**:

> Although sufficient performance was secured through prompt/serving optimization, this
> phase internalizes **Domain Tool Routing** into the model via LoRA so that accurate
> control-command JSON is produced **even under a minimal prompt** — reducing the
> dependency on a long, hand-tuned system prompt.

### The experiment that proves it
| Condition | Prompt | What it measures |
|---|---|---|
| **Base + Full prompt** | `tool_planning_system.txt` (production long prompt) | current operating standard |
| **Base + Minimal prompt** | 4-line planner prompt (below) | how much the long prompt was carrying |
| **SFT + Minimal prompt** | same minimal prompt | whether routing is now *in the weights* |

**Success = `SFT+Minimal  >  Base+Minimal`, and ideally `SFT+Minimal ≈ or > Base+Full`.**

### Minimal prompt (frozen for the experiment)
```text
You are the V-CORE tool planner.
Given a user command, select exactly one tool and produce valid JSON arguments.
Do not explain. Do not invent missing IDs. If required information is missing,
return the clarify tool instead of guessing.
```

---

## 1. Ground truth: tools & label format (NON-NEGOTIABLE — matches production)

The dataset is grounded on the **real** production contracts in
`web/services/chatbot-backend/app/tools/contracts.py`, **not** illustrative names like
`assign_transport_order`. The 9 real tools:

| Tool | Required args | Optional |
|---|---|---|
| `move_to_station` | `station_id:int` | — |
| `run_station_task` | `station_id:int` | `priority: normal\|high` |
| `inspect_station` | `station_id:int` | — |
| `cancel_command` | `command_id:str` | — |
| `start_simulation` | — | `agv_count:int`, `speed_multiplier:num`, `simulation_name:str`, `acceptance[]` |
| `stop_simulation` | — | — |
| `pause_simulation` | — | — |
| `resume_simulation` | — | — |
| `set_sim_speed` | `speed_multiplier:num` | — |

**Label JSON shape** = exactly what the gateway parses today (`llm_gateway.py`):
```json
{"name": "move_to_station", "arguments": {"station_id": 3}}
```
**No-tool / clarify** uses the production decline sentinel (`_DECLINE_NAMES` in
`llm_gateway.py` already accepts `none`/`clarify` as a terminal state):
- negative / out-of-scope / status chit-chat → `{"name": "none", "arguments": {}}`
- missing required arg / ambiguous / invalid value → `{"name": "clarify", "arguments": {"message": "<question>"}}`

`acceptance[]` items match the F4 contract: `{"metric","comparator","threshold"}` with
metric ∈ {throughput, avg_wait_sec, collision_count, uptime_ratio, active_agvs},
comparator ∈ {">=","<=","=="}.

---

## 2. Dataset (SFT-1)

Total **~450** rows: **Train 300 / Val 50 / Test 100**, stratified per category.
Built by template + slot expansion (deterministic, label-by-construction) extending the
existing 133-case v2 suite. Test set is **held out** — no prompt string overlaps train/val.

### Category mix (over-weights the two SFT targets)
| Category | Tool target | Train | Val | Test | Why |
|---|---:|---:|---:|---:|---|
| disambiguation | move/run/inspect by verb | 60 | 10 | 20 | **SFT target** (verb→tool sensitivity) |
| kpi_acceptance | start_simulation + acceptance[] | 54 | 9 | 18 | **SFT target** (nested array extraction) |
| move_to_station | move_to_station | 36 | 6 | 12 | core routing |
| run_station_task | run_station_task | 30 | 5 | 10 | core routing |
| inspect_station | inspect_station | 24 | 4 | 8 | core routing |
| sim_lifecycle | start/stop/pause/resume/set_sim_speed | 36 | 6 | 12 | lifecycle verbs |
| missing_parameter | clarify | 24 | 4 | 8 | decline discipline |
| invalid_parameter | clarify | 15 | 3 | 6 | range/enum decline |
| negative_control | none | 12 | 2 | 4 | don't act |
| state_dependent | lifecycle (coherent) | 9 | 1 | 2 | context-coherent verb |
| **Total** | | **300** | **50** | **100** | |

### Variation banks (the augmentation that makes 133 → 450)
- **Verbs:** send / move / dispatch / drive / 보내 / 이동 / 가 (→move); run / work / do / execute / 작업 / 수행 / 돌려 (→run); check / inspect / look at / 확인 / 검사 / 점검 (→inspect); start/launch/begin, stop/halt/shut down, pause/freeze/hold, resume/continue/pick up.
- **Station expressions:** `S{n}` · `station {n}` · `workstation {n}` · `{n}번 스테이션` · `스테이션 {n}` · named aliases (`loading area`→1, `shipping area`→12, `warehouse`→10) documented in `data/alias_map.json`.
- **AGV expressions:** `AGV-0{n}` · `AGV {n}` · `{n}호기` · `first robot/첫 번째 로봇` (cosmetic; current tools are single-AGV so AGV id is not a label arg — used only to vary surface form).
- **Languages:** ko + en, roughly balanced per category.

---

## 3. Phases & checklist

### Phase SFT-1 — Dataset creation ✅ COMPLETE (2026-06-11)
- [x] Build generator `docs/sft/scripts/build_sft_dataset.py` (extends v2 templates; label-by-construction).
- [x] Emit `data/train.jsonl` (300), `data/val.jsonl` (50), `data/test.jsonl` (100).
- [x] Emit `data/alias_map.json` + `data/dataset_card.md` (counts, schema, split rule).
- [x] Self-check: zero prompt overlap (450/450 unique); **450/450 labels valid** against live `ToolRouter`; per-category counts exact.
- [x] Write `docs/sft/RESULT_SFT1.md`.

### Phase SFT-2 — LoRA / QLoRA training ✅ COMPLETE (2026-06-11)
- [x] Target model = the **deployed production base `Qwen/Qwen3.5-2B`** (HF source of Ollama
      `qwen3.5:2b`, GGUF blob `sha256-b709d815…`). Confirmed identical base; not substituted.
- [x] Convert JSONL → chat-format SFT samples (minimal prompt as system, user command, assistant = label JSON; prompt tokens masked).
- [x] Training config `data/lora_config.yaml` (rank, alpha, dropout, lr, epochs, max_seq, target_modules).
- [x] Run QLoRA on host GPU (RTX 4060 Ti, dedicated venv `C:/Users/PC/sft-train-venv`). 3 epochs, ~6.8 min, eval_loss 0.0315→0.0029. `scripts/train_lora.py`.
- [x] Export adapter (`data/adapter/`) + merged fp16 (`data/merged-fp16/`) + GGUF q4_k_m (`data/vcore-toolrouter.gguf`) loading on llama.cpp :8080. Smoke test 6/6 under minimal prompt.
- [x] Write `docs/sft/RESULT_SFT2.md`.

### Phase SFT-3 — Evaluation ✅ COMPLETE (2026-06-11) — PASS
- [x] Eval harness `docs/sft/scripts/eval_sft.py` reusing the v2 scorer over `data/test.jsonl`.
- [x] Ran the 3-way matrix on the held-out test set, all served on llama.cpp :8080 for parity:
      **Base+Full 49% · Base+Minimal 12% · SFT+Minimal 96%.**
- [x] Per-category table in `docs/sft/RESULT_SFT3.md` (SFT targets: disambiguation 95%, kpi 100%).
- [x] Verdict: **all 3 gates pass** — SFT+Min ≫ Base+Min, SFT+Min ≫ Base+Full, KPI/Missing-Param not regressed.

### Phase SFT-5 — Close the start+speed gap + extra acceptance metrics ✅ COMPLETE (2026-06-15)
- [x] Added `start_with_speed` (30/5/10) — `start_simulation` with **both** `agv_count` +
      `speed_multiplier` (1x/1.5x/2x/3x, EN+KO, ~25% with `acceptance[]`); the pairing was missing
      (all original `speed_multiplier` labels were on `set_sim_speed`).
- [x] Added `kpi_acceptance_metrics` (24/4/8) — `start_simulation` + `acceptance[]` on the
      zero-coverage metrics `bottleneck_rate` (% 0–100), `uptime_ratio` (0–1), `active_agvs` (count),
      phrased as single-run verifiable goals (no optimize verb → don't collide with the optimizer).
      Dataset 450→**531 rows**, all re-validated; new categories appended last so existing splits are
      unperturbed.
- [x] Retrained (eval_loss 0.0033). Fixed a venv `pandas`-3.x WMI-probe import hang in `train_lora.py`.
- [x] **Quant: q5_k_m, not q4_k_m** — q4 washed out the new 30-row distinctions (start_with_speed 0/10,
      reverted to base `agv_speed_multiplier`/`run_simulation`); q5_k_m preserves them at +0.07 GB.
- [x] Eval SFT+Minimal **98.3% (116/118)**: start_with_speed 10/10, kpi_acceptance_metrics 8/8, no
      regression elsewhere. Removed the SFT-4 boundary aliases (`llm_gateway.py`); verified end-to-end
      through the real routing gateway. See DONE.md "SFT-5".
- Out of scope (confirmed already implemented elsewhere): "find the *optimal* AGV count under a
  bottleneck %" is the keyword-routed `optimize_agv_count` node (`domain/optimization.py`), upstream
  of the tool router — not an SFT concern.

### Success criteria (gate)
1. `SFT+Minimal` Task Success **> `Base+Minimal`** (strict, non-overlapping is ideal).
2. `SFT+Minimal` **≈ or >** `Base+Full` Task Success (target ≥ Base+Full − noise).
3. KPI-acceptance and Missing-Param **not regressed** below Base+Full.

---

## 4. Constraints & notes
- **Host Python is available** (`C:/Users/PC/anaconda3/python.exe`) and is used for dataset
  generation, label validation, LoRA training, and eval. The full backend *stack*
  (postgres/redis/ollama) still runs in Docker, but Python tooling does **not** require it.
- **Base model is fixed to production `Qwen/Qwen3.5-2B`** (= Ollama `qwen3.5:2b`) for
  benchmark comparability — see §1 / SFT-2.
- Grade against the **fixed Phase-2-B baseline** (one blob, reasoning-off, llama.cpp 9559).
- llama.cpp serving commands + model/blob paths are documented in `CLAUDE.md` and `AGENT.md`.
- Perforce: new files under `docs/sft/` are adds; reconcile in P4V.
