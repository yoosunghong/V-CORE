# Phase 2.5 — Pre-SFT Semantic Diagnostic (prompt lever)

Date: 2026-06-11
Status: **Complete.** The cheap prompt/few-shot lever was tested on the two
layer-immune Phase-3 target categories *before* commissioning any fine-tuning, as
§3.8 of [BENCHMARK_PHASE2_PHASE3_PLAN.md](BENCHMARK_PHASE2_PHASE3_PLAN.md) requires.

**Decision (updated 2026-06-11): both Phase-3 target categories are now resolved by free
levers — `kpi_acceptance` by the enriched prompt, and `disambiguation` by the llama.cpp 9559
reasoning-off serving regime (91.7%). Phase 3 LoRA SFT is closed out as unnecessary.** See the
[serving-lever experiment](#serving-lever-experiment-on-disambiguation--resolved-phase-3-not-needed-2026-06-11)
section below for the resolving run.

- Builds on: [PHASE2B_FULL_RESULTS.md](PHASE2B_FULL_RESULTS.md) (fixed-layer baseline).
- Runner: [scripts/phase25_diagnostic.py](../../web/services/chatbot-backend/scripts/phase25_diagnostic.py)
  (reuses the exact Phase-2 `run_cell`/`aggregate_cell` scoring).
- Enriched prompt: [app/prompts/templates_phase25/](../../web/services/chatbot-backend/app/prompts/templates_phase25/).
- Raw: [raw/phase25/phase25_prompt_lever.json](raw/phase25/phase25_prompt_lever.json).
- Run: `python scripts/phase25_diagnostic.py --providers ollama --repeats 5`
  (Ollama `:11434`, `qwen3.5:2b`, identical GGUF blob as Phase 2-B, **layer ON = A2 config**).

---

## TL;DR

The §3.8 hypothesis — that part of the apparent "model limitation" on the two
Phase-3 targets is a **prompt/serving artifact, not intrinsic capability** — is
confirmed for one category and refuted for the other:

| Category (Ollama, layer ON, R=5, n=50–60) | Baseline prompt | **Enriched prompt** | Δ | CIs |
|---|---|---|---|---|
| **`kpi_acceptance`** | 20.0% [11.2–33.0] | **92.0% [81.2–96.8]** | **+72.0 pp** | **non-overlapping** |
| **`disambiguation`** | 58.3% [45.7–69.9] | 60.0% [47.4–71.4] | +1.7 pp | fully overlapping |
| Combined (both target cats) | 40.9% [32.2–50.3] | **74.5% [65.7–81.8]** | +33.6 pp | non-overlapping |

The baseline numbers reproduce Phase 2-B's A2 exactly (kpi 18–22%, disambiguation
60%), confirming the harness is consistent and the only variable is the prompt.

---

## What the enriched prompt changed (and what it cannot)

The only difference between cells is the `tool_planning_system` template. The
enriched variant adds **two plain-text lines** to the shipped prompt:
1. a verb→tool mapping line (go/move→`move_to_station`, work/run→`run_station_task`,
   check/inspect→`inspect_station`), and
2. a compact `acceptance`-array spec (the `metric`/`comparator` enums + three phrase
   mappings: "throughput at least N", "average wait under N s", "zero collisions").

No gold values from the suite were leaked — the worked thresholds taught in the
prompt (e.g. 100/8) differ from the test cases (70/12/0).

### `kpi_acceptance` was a prompt-omission artifact, not a capability limit
The **shipped** `tool_planning_system` prompt never mentions the `acceptance` array
at all — the structure existed only in the tool JSON schema. Once the prompt names
the enums and the three phrase mappings, Ollama emits correct nested
`acceptance[]` items **92%** of the time (10/50 → 46/50), at zero training cost. The
Phase-2-B reading of this category as "model-limited (Ollama 18–22%)" was wrong:
**it was an instruction gap.** This category is therefore **removed from Phase 3
scope.**

### `disambiguation` is a genuine residual the prompt cannot move
The same enriched prompt **did not move** disambiguation (58.3% → 60.0%, overlapping
CIs). The failure mode is systematic and instruction-resistant: the model collapses
**run/move verbs into `inspect_station`** even with an explicit verb→tool line in the
prompt:

| Prompt | Expected | Actual |
|---|---|---|
| "Work station 3/10" · "스테이션 5/9 작업해" | `run_station_task` | `inspect_station` |
| "Go to station 3" | `move_to_station` | `inspect_station` |

That the 2B model **ignores a direct, unambiguous instruction** is itself the
fine-tuning signal: this is verb→tool *behavior* that examples-in-prompt do not fix,
which is exactly what task-specific SFT addresses.

> ⚠️ **Important destabilization finding.** A first, heavier enriched prompt — one
> that added a *block of inline JSON verb examples* (`{"name":"move_to_station",...}`)
> — collapsed **both** categories to **0%**: the 2B model returned empty content /
> no tool call and the layer read it as a decline. Removing the JSON-example block
> and keeping a single plain-text verb line restored stability. Lesson for Phase 3
> data/prompt work: **qwen3.5:2b is sensitive to system-prompt length and to inline
> JSON exemplars** under `format:json`+tools; keep instruction prose compact.

---

## Decision — Phase 3 go/no-go (per the §4.1 revised gate)

The revised gate requires a residual that (1) fails on semantics not format, (2)
**survives the §3.8 cheap levers**, and (3) is learnable from examples.

| Phase-3 candidate | Survives prompt lever? | Verdict |
|---|---|---|
| `kpi_acceptance` | ❌ no — prompt lifts it 20%→92% | **Dropped.** Ship the prompt, not SFT. |
| `disambiguation` | ✅ yes — 58%→60%, unmoved | **Sole surviving SFT candidate.** |

**Recommended next actions, in order:**

1. **Ship the enriched prompt to production now.** It is a free, CI-backed +72 pp on
   `kpi_acceptance` (and +33.6 pp on the combined target set) with no regression
   observed on the categories tested. This raises overall task success without any
   model change. *(Promote `templates_phase25/tool_planning_system.txt` into the
   shipped template, then re-run the full 133-case suite to confirm no regression on
   the other 10 categories before committing.)*
2. **Try one serving lever on `disambiguation` before SFT.** Phase 2-B already shows
   the *same GGUF blob* scores `disambiguation` **80% on reasoning-off llama.cpp vs
   60% on Ollama** — a +20 pp serving-regime effect on identical weights. Re-measure
   disambiguation with the enriched prompt on the project llama.cpp 9559 binary; if it
   lands ~80%, the residual shrinks further and **Phase 3 may not be needed at all.**
3. **Only if disambiguation still has a material gap after (1)+(2):** scope Phase 3
   LoRA SFT to **`disambiguation` alone** — a single, narrow verb→tool-selection
   objective. Because overall task success is already ~75% and the prompt+serving
   levers carry `kpi_acceptance`, this Phase 3 is a **deliberate portfolio artifact,
   not a production necessity** — label it as such.

**Net effect on Phase 3 scope:** narrowed from *two* categories (Phase 2-B) to *one*
(`disambiguation`), and gated behind a serving experiment that may close it for free.

---

## Full-suite regression confirmation — **SHIPPED** (2026-06-11)

Before promoting the enriched prompt, action #1's caveat was honored: the enriched
`tool_planning_system.txt` was copied into the **shipped** template
(`app/prompts/templates/`, now byte-identical to `templates_phase25/`) and the **full
133-case Phase-2 suite** was re-run (Ollama, layer ON = A2, R=5, n=665) to confirm no
regression on the other 10 categories. Raw:
[raw/phase25_full_regression/phase2_validation_ablation.md](raw/phase25_full_regression/phase2_validation_ablation.md).

**Gate:** ship only if (1) the `kpi_acceptance` gain holds **and** (2) no other category
regresses **beyond CI overlap** vs the PHASE2B A2 column. **Both met → shipped.**

| Category | A2 baseline | A2 enriched | Δ | CI overlap vs baseline? |
|---|---|---|---|---|
| **kpi_acceptance** | 22.0 | **94.0** [83.8–97.9] | **+72.0** | **separated (the win, holds)** |
| positive_invocation | 100.0 | 92.9 | −7.1 | overlap |
| negative_control | 81.4 | 67.1 | −14.3 | overlap |
| ambiguous | 76.0 | 64.0 | −12.0 | overlap |
| parameter_extraction | 100.0 | 100.0 | 0 | overlap |
| multi_parameter | 100.0 | 100.0 | 0 | overlap |
| missing_parameter | 51.7 | 41.7 | −10.0 | overlap |
| long_request | 100.0 | 100.0 | 0 | overlap |
| invalid_parameter | 56.0 | 60.0 | +4.0 | overlap |
| disambiguation | 60.0 | 63.3 | +3.3 | overlap (unmoved, as predicted) |
| sequential | 90.0 | 90.0 | 0 | overlap |
| state_dependent | 68.0 | 58.0 | −10.0 | overlap |
| **Overall task success** | **75.9** | **77.1** [74–80] | **+1.2** | — |

The `kpi_acceptance` lift not only held at full scale but **landed at 94%** (>the 92%
probe). No category regressed beyond CI overlap, so the gate passes. **Honesty note:**
there is a consistent *soft* downward drift on the decline/eager-error categories
(negative_control −14.3, ambiguous −12.0, missing_parameter −10.0, state_dependent −10.0,
positive_invocation −7.1) — each within CI overlap individually, but the uniform direction
is consistent with the logged "2B is sensitive to system-prompt length" finding. It is
noise-level per the stated criterion and outweighed by the +72 pp kpi win (overall +1.2 pp),
but flagged here for the record and as a watch-item if the prompt is enriched further.

## Serving-lever experiment on `disambiguation` — **RESOLVED, Phase 3 not needed** (2026-06-11)

Action #2 above (the one remaining open item) has now been executed: re-measure the sole
surviving residual, `disambiguation`, on the **project llama.cpp 9559 binary reasoning-off**
with the shipped (enriched) prompt, to test whether the +20 pp serving-regime effect Phase 2-B
saw on the *same GGUF blob* (llama.cpp 80% vs Ollama 60%) reproduces and closes the gap.

- Server: `Intermediate/llama-build/bin/Release/llama-server.exe`, **version 9559 (`715b86a36`)**,
  serving the identical Phase-2-B blob `sha256-b709d815…` (2.74 GB) on `:8080`,
  `-ngl 99 -c 8192 --jinja --reasoning off --reasoning-budget 0` (`thinking = 0`,
  `system_fingerprint: b9559-715b86a36`).
- Runner: `python scripts/phase25_diagnostic.py --providers llama_cpp --repeats 5`
  (host anaconda Python 3.13), layer ON = A2/B2 config, R=5, seed 1234.
- Raw: [raw/phase25_llamacpp/phase25_prompt_lever.json](raw/phase25_llamacpp/phase25_prompt_lever.json) (+ `run.log`).

| Category (llama.cpp 9559, reasoning-off, layer ON, R=5) | Result | Phase 2-B prediction | Ollama (enriched, full-suite) |
|---|---|---|---|
| **`disambiguation`** | **91.7% [81.9–96.4]** (55/60) | ~80% | 63.3% |
| `kpi_acceptance` | 100.0% [92.9–100.0] (50/50) | (n/a) | 94.0% |

The `disambiguation` number not only reproduced the Phase-2-B serving effect, it **exceeded the
~80% prediction, landing at 91.7%** — a **+28 pp** lift over the same blob on Ollama with the same
prompt (63.3% full-suite / 60.0% probe). Baseline and enriched cells are identical here because the
enriched prompt was promoted into the shipped templates on 2026-06-11 (the two template dirs are now
byte-identical), so this is purely the **serving regime** moving the residual, not the prompt.

The residual is now a single, rare prototype — the *same* verb-collapse failure as on Ollama,
**`"Work station 3."` → `inspect_station`** instead of `run_station_task` — but it occurs only
**5/60 (8.3%)** on reasoning-off llama.cpp versus ~40% on Ollama.

### Decision: `disambiguation` drops out of Phase 3 — **Phase 3 SFT is not required**
Action #2's gate was: *"if it lands ~80%, the residual shrinks further and Phase 3 may not be
needed at all."* It landed at **91.7% > 80%**. Combined with the prompt lever already carrying
`kpi_acceptance` (→94–100%), **both** former Phase-3 target categories are now resolved by the
**free** prompt+serving levers, with **no fine-tuning**:

| Former Phase-3 candidate | Resolved by | Result | Phase 3? |
|---|---|---|---|
| `kpi_acceptance` | enriched prompt (shipped) | 94% Ollama / 100% llama.cpp | ❌ dropped |
| `disambiguation` | serving regime (llama.cpp 9559 reasoning-off) | **91.7%** llama.cpp | ❌ dropped |

**Net: Phase 3 LoRA SFT is closed out as unnecessary for the demo.** The recommended production
serving path is **llama.cpp 9559 reasoning-off + the shipped enriched prompt**, which carries both
residuals without any model change. (If the deployment is pinned to Ollama for other reasons,
`disambiguation` remains at ~60–63% and the verb-collapse SFT objective from action #3 is the only
remaining lever — but that is now an Ollama-serving artifact, not an intrinsic model limit, since
the identical weights score 91.7% under reasoning-off llama.cpp.)

---

## Reproducibility

- llama.cpp serving lever: project binary **9559 (`715b86a36`)**, `:8080`, same blob
  `sha256-b709d815…`, `-ngl 99 -c 8192 --jinja --reasoning off --reasoning-budget 0`; R=5, seed 1234;
  22 cases (10 `kpi_acceptance` + 12 `disambiguation`) → 50 / 60 measurements per category; Wilson 95% CIs.
- Ollama `:11434`, `qwen3.5:2b` (`sha256-b709d815…`, the Phase-2-B blob), `think:false`,
  `num_ctx 2048`, `num_predict 128` (160 in probes), temperature 0.2 (0.0 on repair).
- Layer ON = A2 config: `structured_retry_count=1`, fallback on, `enable_decline_retry`,
  `enable_range_validation`. Only the `prompt_store` differs between the two cells.
- 22 cases (10 `kpi_acceptance` + 12 `disambiguation`), R=5, seed 1234, randomized
  order per repeat → 50 / 60 measurements per category per cell; Wilson 95% CIs.
- Baseline cell reproduces Phase-2-B A2 per-category numbers, confirming consistency.
