# Phase 2 Results — Validation-Layer Ablation (v2 benchmark)

Date: 2026-06-11
Status: **Phase 2 complete — executed end-to-end.**
Model: `qwen3.5:2b` (one GGUF blob, served on both Ollama and llama.cpp).
Suite: **133 labeled cases** across 12 categories (en + ko), **R=5 repeats** →
665 measurements per cell. Every rate carries a Wilson 95% CI.

- Design: [BENCHMARK_PHASE2_PHASE3_PLAN.md](BENCHMARK_PHASE2_PHASE3_PLAN.md)
- Generated tables (source of truth): [raw/phase2_validation_ablation.md](raw/phase2_validation_ablation.md)
- Machine-readable: `raw/phase2_validation_ablation.{json,csv}`
- Case suite: [cases/v2/](cases/v2/) (static JSONL, regenerate with `scripts/generate_v2_cases.py`)
- Run command: `python scripts/benchmark_v2.py --providers ollama,llama_cpp --layers off,on --repeats 5 --output-dir ../../../docs/benchmark/raw`

---

## TL;DR

The validation layer (repair retry + deterministic rule-based fallback) is **not
provider-neutral — it does the opposite thing to each provider**:

| Provider | Layer OFF (intrinsic) | Layer ON (production) | Δ |
|---|---|---|---|
| **Ollama** | **75.2%** [72–78] | 54.3% [50–58] | **−20.9 pp** |
| **llama.cpp** | 53.5% [50–57] | 66.2% [62–70] | **+12.6 pp** |

(Headline = Task Success Rate: correct tool **and** correct arguments. n=665/cell.)

- For **Ollama**, the layer is **net-harmful**: the repair retry coerces correct
  *declines* into hallucinated tool calls.
- For **llama.cpp**, the layer is **net-helpful**: the deterministic fallback
  rescues a model that almost never emits valid JSON on the first try.
- The single best configuration in the whole matrix is **A1 — raw Ollama with the
  validation layer switched off (75.2%)**. The shipped production path (A2) is
  *worse* than doing nothing.

This is exactly the "separate the model from the system" result Phase 2 was
designed to produce, and the CIs make it statistically defensible (A1 vs A2 CIs
do not overlap; B1 vs B2 do not overlap).

---

## 1. Why the layer helps one provider and hurts the other

The two providers have **opposite intrinsic failure modes**, and the layer
interacts with each differently.

### Ollama — capable but eager (the retry breaks it)

- First-pass schema-valid **74.1%**, JSON parse **83.3%** — Ollama can already
  produce well-formed tool calls.
- It also *declines* reasonably: clarification-appropriate **64.3%** with the
  layer off.
- Turning the layer **on** triggers a repair retry on **26.2%** of cases. The
  repair prompt ("Return exactly one valid JSON object with name and arguments
  matching the tool schema") is **coercive** — it tells a model that correctly
  emitted *no* tool to go emit one. Result: the decline categories collapse.

| Category | A1 (off) | A2 (on) |
|---|---|---|
| negative_control | 94.3% | **2.9%** |
| ambiguous | 86.0% | **0.0%** |
| missing_parameter | 61.7% | **0.0%** |

  Schema-validity goes *up* (+24.1 pp → 98.2%) while task success goes *down*
  (−20.9 pp). The retry is optimizing the wrong metric: it makes the output
  *well-formed* by making it *wrong*. Of the retries that fired, only **5.7%**
  ended in a correct result ("repair success").

### llama.cpp — weak JSON but conservative (the fallback saves it)

- First-pass schema-valid **24.4%** — on this harder bilingual suite llama.cpp
  rarely emits a parseable tool call on the first shot.
- But it is **conservative**: clarification-appropriate **93.9%**, and it nails
  every decline category (negative/ambiguous **100%**) by simply not acting.
- With the layer **off** (B1) it therefore *passes the negative categories for
  free but fails almost every positive one* (multi_parameter 4%, long_request
  12%, sequential 8%, kpi 0%).
- With the layer **on** (B2) the **rule-based fallback fires on 38.6%** of cases
  (correct 46.3% of the time) and the retry on 76.4%, dragging positives up:
  parameter_extraction 45.5%→**100%**, disambiguation 48%→83%, kpi 0%→**60%**,
  positive 66%→86%.

  So **B2's gains are carried by deterministic regex code, not the model.** That
  is a legitimate product (it works), but it must be reported honestly: the
  "llama.cpp agent" is really "llama.cpp + a hand-written intent parser."

### The Phase-1 confound, now explained

Phase 1 (n=12) noted llama.cpp "declined negative controls better" and Ollama
"produced valid JSON more often." Both are confirmed at n=665 and are two facets
of the same axis: **Ollama is eager + JSON-capable; llama.cpp is conservative +
JSON-weak.** The validation layer rewards the conservative model and punishes the
eager one.

---

## 2. Two concrete, actionable bugs surfaced

1. **Repair-retry decline-coercion (severity: high).** The retry prompt cannot
   express "no tool is correct," so every retry ends in a tool call. Fix: allow a
   canonical "no tool / clarify" sentinel in the repair prompt and accept it as a
   valid terminal state. Expected effect: recover ~20 pp of Ollama task success
   for free, with no model change. *This is the highest-ROI fix in the project.*

2. **Validator has no value-range checks (severity: medium).** `invalid_parameter`
   is near-zero for the eager configurations (A1 4%, A2 0%): station −1, speed 0,
   speed −2x, station 999 all pass straight through because `ToolRouter.validate`
   only type-checks, never range-checks. Fix: add range/enum bounds to the
   validator so out-of-range values are rejected (→ repair or decline) instead of
   silently dispatched to UE5.

---

## 3. What the layer can and cannot fix (per-category)

- **Fully model-limited, layer can't help:** `kpi_acceptance` (nested
  `acceptance[]` extraction — A1/A2 ~20%, B1 0%) and `multi_parameter`
  (llama.cpp 4–10%). These are *semantic* extraction tasks; neither the retry nor
  the regex fallback understands them. **This is the strongest case for Phase 3
  fine-tuning.**
- **Verb-sensitivity gap:** `disambiguation` ~60% on Ollama (run vs move vs
  inspect on the same station) — the Phase-1 `run_station_task`→`inspect_station`
  error reproduces at scale.
- **Layer-rescuable (format, not meaning):** the positive/parameter categories on
  llama.cpp — pure JSON-shape failures that the fallback fixes.

---

## 4. Latency cost of the layer

| Cell | mean (ms) | p95 | mean **with** retry | mean **without** |
|---|---:|---:|---:|---:|
| A1 Ollama off | 1360 | 2106 | — | 1360 |
| A2 Ollama on | 1663 | 3281 | **2978** | 1197 |
| B1 llama.cpp off | 1499 | 1559 | — | 1499 |
| B2 llama.cpp on | 2893 | 3911 | **3335** | 1461 |

A retry roughly **doubles** a prompt's latency (≈ a second LLM call), as
predicted. For Ollama that extra latency *buys negative value*. For llama.cpp,
B2's 76% retry rate makes it the slowest cell (mean 2.9 s) — the fallback rescue
is real but expensive.

---

## 5. Phase-3 go / no-go decision

Per the plan's gate (fine-tune only if first-attempt success is the bottleneck,
the layer can't cheaply close it, and the failing categories are learnable):

**Recommendation: do the two free fixes in §2 first; then a *narrow, scoped*
Phase-3 fine-tune is justified — but for semantics, not JSON shape.**

- The biggest Ollama loss (−20.9 pp) is **not** a model problem — it is the
  coercive retry. Fixing the prompt recovers it at zero training cost. Do this
  before any fine-tuning, or Phase 3 will be measured against a self-inflicted
  baseline.
- After that fix, the residual gaps are **`kpi_acceptance` and
  `multi_parameter`** — genuinely model-limited, learnable structured-output
  tasks. These are the right and only target for LoRA SFT (Deliverable 4),
  over-weighted in the training mix as the plan already specifies.
- **Do not** fine-tune to fix `invalid_parameter`; that is a validator change, not
  a model deficiency.
- llama.cpp's 24% first-pass JSON is a format problem SFT fixes well, but we would
  fine-tune the shared base and can then re-serve on either runtime.

Net: Phase 3 is **conditionally GO**, scoped to KPI/multi-parameter semantics,
**after** the §2 fixes re-baseline Phase 2.

---

## 6. Portfolio framing (Deliverable 6)

The headline is a *judgment* result, not a leaderboard number:

> "The production validation layer helps a weak model and hurts a strong one. On
> the same task and prompt, switching it on moved Ollama −21 pp and llama.cpp
> +13 pp. The shipped path was beaten by raw Ollama. We traced it to a coercive
> repair prompt and a regex fallback doing the model's job, quantified each with
> 95% CIs across 665 trials/cell, and turned it into a prioritized fix list and a
> scoped fine-tuning decision."

That demonstrates eval design, ablation thinking, statistical literacy, and the
ability to separate *model* from *system* — the senior signals the plan's
Deliverable 6 targets.

---

## Reproducibility / controls

- Same GGUF blob on both providers; `num_ctx 2048`, matching `num_predict`,
  llama.cpp `-ngl 99`. Providers served **sequentially**, not concurrently.
- Identical validation logic per provider: `LlamaCppLlmGateway` subclasses
  `OllamaLlmGateway` and overrides only `_post_chat`. Ablation is via constructor
  toggles (`structured_retry_count`, `enable_rule_based_fallback`,
  `enable_argument_normalization`), so both providers run byte-identical layer code.
- Cases are static version-controlled JSONL; randomized prompt order per repeat
  (seed 1234). Gold labels are constructed by the generator, never scraped from
  the model under test.
- Caveat: `argument_normalization` was left **off** for the layer-ON cells (it is
  not in the production path yet); it is wired and ablatable via
  `--enable-normalization` for a follow-up measurement.
