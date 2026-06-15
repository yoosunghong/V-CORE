# Making a 2B Local LLM Reliable Enough to Drive a Factory — Without Fine-Tuning

**A portfolio case study in LLM evaluation, system ablation, and engineering judgment.**

Author: AI systems engineer / experimental researcher · Date: 2026-06-11
Project: VCORE — AI Twin platform; the tool-planning path that turns a chat
message ("Run station 3 if throughput stays above 70/h") into a validated tool
call that drives a live Unreal Engine 5 AGV cell.

Source artifacts (all reproducible, CI-backed):
[BENCHMARK_PHASE2_PLAN.md](BENCHMARK_PHASE2_PLAN.md) ·
[PHASE2_RESULTS.md](PHASE2_RESULTS.md) ·
[PHASE2B_FIX_VALIDATION.md](PHASE2B_FIX_VALIDATION.md) ·
[PHASE2B_FULL_RESULTS.md](PHASE2B_FULL_RESULTS.md) ·
[PHASE25_DIAGNOSTIC.md](PHASE25_DIAGNOSTIC.md)

---

## The one-line story

> I had a 2B local model that looked too weak to ship and an obvious instinct to
> fine-tune it. Instead I built a 2,660-trial statistical benchmark, used it to
> prove the production "fix" layer was *hurting* my best model by −21 pp, repaired
> that, then closed both of the two remaining gaps — **KPI extraction 22%→94%** and
> **tool disambiguation 63%→92%** — with a three-line prompt change and a serving-flag
> change. **Fine-tuning was cancelled. Nothing was trained. The numbers carry it.**

The deliverable isn't an accuracy leaderboard. It's a *decision*, made under
constraints, defensible with confidence intervals.

---

## 1. Ollama vs llama.cpp — the question that started it

The agent runs a small local model (`qwen3.5:2b`) and can be served two ways:
**Ollama** and **llama.cpp**. The original Phase-1 smoke test (12 prompts) claimed
Ollama produced valid JSON more often and llama.cpp declined bad inputs better —
but with n=12, *every percentage point was one prompt*. "91.7% vs 58.3%" was a
difference of **four prompts**. None of it was conclusive.

A real comparison had to control everything: **one identical GGUF blob**
(`sha256-b709d815…`) served on both runtimes, same context window, same decode
params, served sequentially on one GPU so neither contended for VRAM. That made
the providers a clean variable — and set up the deeper question: *how much of what
we see is the model, and how much is the system wrapped around it?*

## 2. Validation Layer Ablation — separating the model from the system

The production path isn't just "call the model." It's a **validation layer**: JSON
extraction → schema validation → a repair retry → a deterministic rule-based
fallback. Phase-1 conflated the model's intrinsic ability with this scaffolding.

So I designed a **2×2 ablation** and made the layer *ablatable* via constructor
toggles (good eval hygiene *and* good production hygiene):

| | Provider only (intrinsic) | Provider + Validation Layer (production) |
|---|---|---|
| **Ollama** | A1 | A2 |
| **llama.cpp** | B1 | B2 |

The layer code is **byte-identical** for both providers (`LlamaCppLlmGateway`
subclasses `OllamaLlmGateway` and overrides only transport), so the ablation
isolates exactly one thing: *what does the layer buy us, per provider?*

## 3. 2,660 Benchmarks — a suite that can actually support a claim

Phase-1's n=12 couldn't. So I built **Benchmark v2**: 133 labeled cases across
**12 categories**, bilingual (English + Korean), with **argument-level scoring**
(the old harness checked *which tool* was picked but never whether the arguments
were right — wrong args silently counted as a pass). Each case runs **R=5 times**.

133 cases × 5 repeats × 4 cells = **2,660 scored executions** (~2,860 LLM calls
including retries). Cases are static, version-controlled JSONL with gold labels
*constructed* by a generator — never scraped from the model under test, so
base-vs-anything comparisons stay honest.

## 4. Wilson CI Analysis — refusing to over-claim

Every rate is reported with a **Wilson 95% confidence interval**, and claims are
only made when CIs separate. This is what turned anecdotes into findings:

| Cell | Task Success | 95% CI | k/n |
|---|---|---|---|
| A1 Ollama OFF | 75.6% | [72.2–78.8] | 503/665 |
| A2 Ollama ON | 75.9% | [72.6–79.0] | 505/665 |
| B1 llama.cpp OFF | 69.0% | [65.4–72.4] | 459/665 |
| B2 llama.cpp ON | 74.0% | [70.5–77.2] | 492/665 |

The CIs do the arguing: A1≈A2 overlap fully → *the layer is statistically neutral
on Ollama*. B1 vs B2 do **not** overlap → *the layer is a real +5.0 pp on
llama.cpp*. No hand-waving — the intervals decide.

## 5. Failure Category Identification — the layer was hurting my best model

The first full run (Phase 2-A) produced the result the whole experiment was built
to find — and it was the *opposite* of comfortable:

| Provider | Layer OFF | Layer ON | Δ |
|---|---|---|---|
| **Ollama** | **75.2%** | 54.3% | **−20.9 pp** |
| **llama.cpp** | 53.5% | 66.2% | **+12.6 pp** |

**The shipped production path (A2) was worse than doing nothing (A1).** The single
best config in the whole matrix was *raw Ollama with the layer switched off.*

Per-category scoring showed exactly why. Turning the layer ON collapsed Ollama's
*decline* categories:

| Category | A1 (off) | A2 (on) |
|---|---|---|
| negative_control | 94.3% | **2.9%** |
| ambiguous | 86.0% | **0.0%** |
| missing_parameter | 61.7% | **0.0%** |

Two providers, two opposite intrinsic personalities: **Ollama is eager and
JSON-capable; llama.cpp is conservative and JSON-weak.** The layer rewarded the
conservative one and punished the eager one. And llama.cpp's "gains" were carried
by **regex fallback firing on 38.6% of cases** — i.e. a hand-written intent parser
doing the model's job. Honest framing: that's "llama.cpp + a parser," not "llama.cpp."

## 6. Prompt Diagnosis — finding the root cause, not just the symptom

The −21 pp wasn't a model problem. The **repair-retry prompt** said, in effect,
"return exactly one valid tool call" — it had no vocabulary for *"no tool is
correct."* So every retry on a correct decline *coerced* a hallucinated tool call.
Of retries that fired, only **5.7%** ended correct.

The fix wasn't one-shot — it took three iterations, each measured:

| Iteration | A2 task success | negative_control | What was still wrong |
|---|---|---|---|
| v1 (add sentinel, still retried) | 39.5% | 35.7% | retry still coerced clean declines |
| v2 (stop retrying, but fell back) | 50.5% | 69.0% | fallback re-acted on declines |
| **v3 (honor a clean decline as terminal)** | **64.3%** | **88.1%** | — |

Plus a second bug the suite surfaced: the validator only **type-checked**, never
**range-checked**, so `station -1`, `station 999`, `speed -2x` flowed straight
through to UE5. Adding range validation moved `invalid_parameter` from ~4% to ~57%.

At full scale, the repair was decisive and **CI-separated**:

| A2 category | Broken layer (2-A) | Fixed layer (2-B) | Δ |
|---|---|---|---|
| negative_control | 2.9% | 81.4% | **+78.5 pp** |
| ambiguous | 0.0% | 76.0% | **+76.0 pp** |
| invalid_parameter | 0.0% | 56.0% | **+56.0 pp** |
| **A2 overall** | **54.3% [50–58]** | **75.9% [73–79]** | **+21.6 pp, non-overlapping** |

The layer went from net-harmful to net-neutral on Ollama and net-positive on
llama.cpp. JSON parse hit **100%**, first-pass schema validity **94%**. The "format
problem" was solved — which *invalidated the original case for fine-tuning* and left
only two stubborn, **semantic** residuals: `kpi_acceptance` and `disambiguation`.

## 7. KPI Acceptance — 22% → 94% with three lines of prompt

`kpi_acceptance` is the hard one: map natural language ("accept only if throughput
≥ 70/h, avg wait < 12s, zero collisions") into a nested `acceptance[]` array. Ollama
scored **18–22%** — it emitted *valid JSON with empty/wrong criteria*, so the schema
passed and the layer was provably blind to it. This looked like the textbook case
for fine-tuning.

Before committing 5–8 days to SFT, I tested the cheapest possible lever (Phase 2.5):
**does the prompt even mention the `acceptance` array?** It didn't. The shipped
system prompt never named it — the structure existed *only* in the tool's JSON
schema. I added **two plain-text lines** (the metric/comparator enums + three phrase
mappings), leaking no gold values:

| `kpi_acceptance` | Baseline prompt | Enriched prompt | Δ |
|---|---|---|---|
| Ollama, layer ON, R=5 | 20.0% [11.2–33.0] | **92.0% [81.2–96.8]** | **+72.0 pp, non-overlapping** |

Confirmed on the full 133-case suite: **22% → 94%**, no other category regressing
beyond CI overlap, overall task success 75.9% → 77.1%. **It was never a model
limitation — it was an instruction gap.** A category I'd flagged for fine-tuning was
closed for free, and dropped from Phase 3 scope.

(A discipline note worth keeping: a *heavier* prompt variant with inline JSON
exemplars collapsed both categories to **0%** — the 2B model is sensitive to
system-prompt length under `format:json`. Compact prose won. I logged it.)

## 8. Serving Diagnosis — the same weights score differently

`disambiguation` (run vs move vs inspect on the same station) did **not** budge
under the prompt lever: 58.3% → 60.0%, fully overlapping. The model collapses
run/move verbs into `inspect_station` even with an explicit verb→tool instruction.
That instruction-resistance was, finally, a genuine fine-tuning signal.

Except the benchmark had already left a clue: on the **same GGUF blob**, the
per-category data showed `disambiguation` at **80% on reasoning-off llama.cpp vs 60%
on Ollama**. A 20-point swing on *identical weights* is a **serving artifact, not a
capability limit**. Before training anything, I rebuilt the project's llama.cpp with
CUDA (it had silently been a CPU-only build) and served the exact blob reasoning-off.

## 9. Disambiguation — 63% → 92% with a serving flag

Re-measured on the project llama.cpp 9559 binary, reasoning-off, with the shipped
enriched prompt:

| `disambiguation` | Ollama (enriched) | **llama.cpp 9559, reasoning-off** |
|---|---|---|
| Task Success, R=5 | 63.3% | **91.7% [81.9–96.4]** |

**63% → 92%** — it not only reproduced the predicted serving effect, it **exceeded**
the ~80% prediction. The residual verb-collapse failure ("Work station 3" →
`inspect_station`) dropped from ~40% of cases on Ollama to **5/60 (8.3%)** here. Same
weights, same prompt — *only the serving regime changed.*

## 10. Problem Solving Without Fine-Tuning — the decision

Both categories that had justified a multi-day LoRA fine-tune were resolved by
**free levers** — one prompt change, one serving-flag change — each verified with
confidence intervals:

| Former Phase-3 target | Resolved by | Result | Fine-tune? |
|---|---|---|---|
| `kpi_acceptance` | enriched prompt (shipped) | 94% Ollama / 100% llama.cpp | ❌ dropped |
| `disambiguation` | serving regime (llama.cpp reasoning-off) | **91.7%** | ❌ dropped |

**Phase 3 LoRA SFT was closed out as unnecessary.** The recommended production path
is `llama.cpp 9559 reasoning-off + the shipped enriched prompt`, which carries both
residuals with **no model change, no training, no GPU-weeks**.

---

## Why this is the senior result

The tempting path was: *the 2B model is weak → fine-tune it.* The rigorous path
found that:

1. The biggest "model weakness" (−21 pp) was a **self-inflicted system bug** in the
   repair prompt — caught only because the ablation separated model from system.
2. The second (KPI extraction) was a **prompt omission** — three lines, +72 pp.
3. The third (disambiguation) was a **serving regime** — one flag, +28 pp on
   identical weights.

Every claim is backed by 665 trials/cell and Wilson CIs; every "fix" was
re-baselined so nothing was graded against a self-inflicted regression. The
artifact that matters isn't a trained checkpoint — it's the **judgment that we
didn't need one, and the evidence that proves it.**

> "Validation layer + a three-line prompt + a serving choice solved almost
> everything. Fine-tuning got scoped down to zero. Here's the cost-benefit, with
> confidence intervals." — that is the deliverable.
