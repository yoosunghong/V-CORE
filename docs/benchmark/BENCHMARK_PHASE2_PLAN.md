# Benchmark Phase 2 & Phase 3 Plan — Structured-Output / Tool-Calling Reliability

Status: **Phase 2 fully executed, including the 2-B fixed-layer re-baseline
(2026-06-11) — see [PHASE2B_FULL_RESULTS.md](PHASE2B_FULL_RESULTS.md).**
Phase 2-B PASS: the fixed validation layer is net-neutral on Ollama and
net-positive (+5 pp, non-overlapping CIs) on llama.cpp — **the layer was *more*
than sufficient, refuting this plan's working hypothesis that it would not be.**
**Phase 2.5 diagnostic now also EXECUTED (2026-06-11) — see
[PHASE25_DIAGNOSTIC.md](PHASE25_DIAGNOSTIC.md).** A 3-line prompt fix lifted
`kpi_acceptance` **20% → 92%** (it was a prompt-omission artifact, not a model
limit → **dropped from Phase 3**); `disambiguation` was **unmoved** (58% → 60%) and
is now the **sole** Phase-3 candidate — itself gated behind an untried serving lever
(reasoning-off llama.cpp scored it 80% vs Ollama 60% on the same blob). The Phase-3
gate (§4.1) was originally a *format/schema* gate that Phase 2-B invalidated; it is
re-scoped to the one surviving **semantic** residual with new metrics (§4.1/§4.5).
Author role: Senior AI systems engineer / experimental researcher
Date: 2026-06-10 (design) · 2026-06-11 (Phase 2-A + 2-B results, plan revised)
Scope: VCORE chatbot-backend LLM tool-planning path (`propose_tool_call`) on local
models (`qwen3.5:2b`), comparing **Ollama** vs **llama.cpp**, then isolating the
**validation layer**, then evaluating **fine-tuning**.

Related artifacts:
- Phase 1 report: [docs/benchmark/README.md](README.md)
- Harness: [app/benchmarks/llm_provider_benchmark.py](../../web/services/chatbot-backend/app/benchmarks/llm_provider_benchmark.py)
- Runner: [scripts/benchmark_llm_providers.py](../../web/services/chatbot-backend/scripts/benchmark_llm_providers.py)
- Gateway under test: [app/infrastructure/llm_gateway.py](../../web/services/chatbot-backend/app/infrastructure/llm_gateway.py)
- Tool contracts: [app/tools/contracts.py](../../web/services/chatbot-backend/app/tools/contracts.py)

---

## 0. TL;DR

| | |
|---|---|
| **Phase 1 (done)** | 12 prompts, Ollama vs llama.cpp, raw-provider reliability + latency. Directional only — not statistically conclusive. |
| **Phase 2 (proposed)** | Expand to **120–200 labeled cases** across 12 categories; measure **provider-only vs provider+validation-layer** with *identical* validation logic, to quantify exactly how much the validation layer (repair retry + deterministic fallback) buys us. |
| **Phase 3 (proposed)** | LoRA fine-tune `qwen3.5:2b` on synthetic + harvested tool-call data **only if** Phase 2 shows the base model is the bottleneck (not the validation layer). Measure base vs fine-tuned with the same v2 suite. |

The single most important Phase-1 caveat: **12 prompts means each percentage point on a
rate metric is 1/12 ≈ 8.3%.** "91.67% vs 58.33% JSON success" is a difference of
**four prompts**. No reliability claim from Phase 1 should be treated as conclusive.

---

# Deliverable 1 — Critical Review of the Existing Benchmark

## 1.1 Is a 12-prompt benchmark statistically meaningful?

**No, not for the conclusions currently drawn from it.** It is a useful smoke test and a
good harness validation, but it cannot support reliability rankings.

- **Resolution floor.** With n=12, the smallest observable difference is 1 prompt = 8.33
  percentage points. Every reported rate is a multiple of 8.33%. "83.33% schema success"
  literally means "10 of 12."
- **Confidence intervals dwarf the effects.** For an observed rate of 58.3% at n=12, the
  Wilson 95% CI is roughly **[32%, 81%]**. For 91.7% it is roughly **[64%, 99%]**. These
  intervals **overlap heavily**, so "Ollama is more reliable at JSON" is not statistically
  established — it is a hypothesis.
- **Per-category n=1.** Several behaviors are represented by a *single* prompt
  (`set_speed`, `run_station_task`, KPI acceptance). A single flake flips the category
  from 100% to 0%. The llama.cpp `set_speed` fallback and the Ollama `run_station_task`
  mis-selection are each **one sample** — possibly noise.
- **No repetition / no variance estimate.** Each prompt is run **once**. Local LLMs at
  `temperature` 0.2 are not deterministic across runs (KV cache, sampling, server load).
  Without repeated trials we cannot separate model error from run-to-run noise.
- **Tool-selection accuracy is confounded.** llama.cpp's higher accuracy (91.67% vs
  66.67%) is driven almost entirely by it **declining the 3 negative-control prompts**
  while Ollama over-fired. That is one *behavioral tendency* (conservative vs eager)
  measured on 3 samples — not a general accuracy result.

**Verdict:** Phase 1 is directionally interesting and the harness is sound, but the sample
is ~10× too small and unreplicated. Treat all Phase-1 rankings as hypotheses to confirm in
Phase 2.

## 1.2 Which prompt categories are underrepresented?

The current 12 prompts (from `DEFAULT_BENCHMARK_PROMPTS`) map to:

| Behavior covered | Count |
|---|---|
| Positive single-tool invocation | 7 |
| Negative control (expect no tool) | 3 |
| Multi-constraint / KPI extraction | 1 |
| Ambiguous | 1 |

Underrepresented or absent:

- **Parameter extraction correctness** — the harness checks *which tool* is chosen but
  **not whether arguments are right** (`station_id`, `speed_multiplier`, `agv_count`).
  This is the single biggest gap.
- **Multi-parameter cases** (e.g. start sim with `agv_count` *and* `speed_multiplier` *and*
  `acceptance`) — 1 prompt.
- **Missing-parameter handling** (e.g. "move the AGV" with no station) — 0 prompts.
- **Invalid parameter values** (station 999, speed -2, agv_count "five") — 0 prompts.
- **Tool disambiguation** (run vs inspect vs move on the same station, distinguished only
  by verb) — minimally covered.
- **Sequential / multi-step** ("move to 2 then run the task") — 0 prompts.
- **State-dependent** ("resume" with no paused sim; "stop" with nothing running) — 0.
- **Korean-language prompts** — 0, despite the rule-based fallback and the product being
  Korean-facing (`_extract_acceptance` parses Korean). The LLM path is tested English-only.
- **Long / noisy natural language** — 0 (only one moderately long KPI prompt).
- **`cancel_command`, `resume_simulation`** — never exercised as expected tools.

## 1.3 Which failure modes are not being tested?

- **Wrong arguments with the right tool** — currently scored as a *success* (tool matched).
- **Hallucinated tools / tool names not in the registry** — `_tool_call_from_parts` raises
  on unknown tools, but no prompt is designed to provoke it.
- **Hallucinated / extra parameters** (`additionalProperties: false` in the schema should
  reject these — untested).
- **Over-firing on negative controls** beyond the 3 generic ones (status queries, greetings,
  meta-questions, out-of-domain requests like "what's the weather").
- **Confirmation-gated destructive actions** (abort/stop) — only one "abort + confirm".
- **Repair-loop behavior** — we record `repair_retry_used` but never test a prompt
  *designed* to fail first then recover, so we can't measure repair *effectiveness*.
- **Timeout / server-error resilience** — `LlmTimeoutError`/`LlmGatewayError` paths are
  never exercised under load.

## 1.4 Which structured-output edge cases are missing?

- JSON wrapped in markdown fences (```json … ```), prose preamble, or trailing commentary
  (the regex `\{.*\}` extraction in `_parse_json_content` should handle some of this —
  untested).
- Multiple JSON objects in one response (regex grabs the widest span — untested).
- Arguments returned as a **JSON-encoded string** vs a nested object (`_tool_call_from_parts`
  handles both branches — untested).
- Empty object `{}` / null arguments for tools that require parameters.
- Numbers as strings (`"station_id": "3"`) and type coercion expectations.
- Unicode / Korean values inside arguments.
- Truncated JSON from `num_predict` cutoff (128 tokens) — likely real and untested.
- Nested-array edge cases for `acceptance` (the only complex nested schema).

## 1.5 Which tool-calling edge cases are missing?

- **Native `tool_calls` vs JSON-content path divergence.** The gateway accepts *both*
  OpenAI-style `message.tool_calls` and free JSON content. Ollama and llama.cpp may take
  different branches; we never isolate which path each provider uses or compare reliability
  per-path.
- **Tool registry scaling.** Only 9 tools are offered. Accuracy under a *larger* tool list
  (distractor tools) is the real-world stressor and is untested.
- **Disambiguation by parameter** (same verb, different station context object passed in
  `station`).
- **Confirmation semantics** (should `abort` *propose* `stop_simulation` or wait?).
- **Multi-tool / sequential intents** in one message.
- **`tool_choice` forcing** behavior differences between providers.

## 1.6 Which latency scenarios are missing?

Current harness measures: first-request, warm average, p95, stddev, cold preload. Missing:

- **Concurrency / load** — all prompts run **sequentially**. No p50/p95/p99 *under N
  concurrent requests*, which is what a multi-user demo actually hits.
- **Latency vs output length** — no breakdown by tokens generated (KPI prompts are slower;
  is that prompt length or output length?).
- **Tail behavior over many runs** — p95 from 12 samples is unstable; true p95/p99 needs
  ≥100 samples.
- **Validation-layer overhead** — the *added* latency of a repair retry (a second LLM call)
  is not separated from base latency. A repair retry roughly **doubles** that prompt's
  latency; this cost is currently invisible.
- **Cold-start under VRAM contention** (Ollama unloads after keep-alive; measure reload).
- **Time-to-first-token** vs total (only total is measured).

## 1.7 Which real-world agent behaviors are missing?

- **Conversational context / multi-turn** — `propose_tool_call` is called with no history;
  real chats reference prior turns ("do it again", "the same one").
- **Mixed-language input** (Korean + English in one message — common for this user base).
- **Clarification instead of action** — a good agent should *ask* on ambiguity, not silently
  decline or guess. We only score "declined" as success; we never test "asked a useful
  question."
- **Refusal of out-of-scope requests** ("delete the database", "what's the weather").
- **Robustness to typos / informal phrasing / voice-transcription artifacts.**
- **Idempotency / repeated commands** behavior.

## 1.8 Benchmark Weaknesses — consolidated list

| # | Weakness | Severity | Fixed in |
|---|---|---|---|
| W1 | n=12 too small; CIs overlap; rankings not significant | Critical | Phase 2 (120–200 cases) |
| W2 | Each prompt run once; no variance estimate | Critical | Phase 2 (≥3 repeats, report CI) |
| W3 | Argument correctness not scored (wrong args = "pass") | Critical | Phase 2 (arg-level scoring) |
| W4 | No missing/invalid-parameter cases | High | Phase 2 cat. 6, 9 |
| W5 | No Korean / mixed-language cases | High | Phase 2 (bilingual set) |
| W6 | Validation-layer effect not isolated | High | Phase 2 (ablation design) |
| W7 | No concurrency/load latency | Medium | Phase 2 (load profile) |
| W8 | Repair-retry cost & effectiveness invisible | Medium | Phase 2 (per-stage metrics) |
| W9 | No multi-step / state-dependent / multi-turn | Medium | Phase 2 cat. 11, 12 |
| W10 | Negative controls only 3, generic | Medium | Phase 2 cat. 2 (expanded) |
| W11 | Structured-output edge cases (fences, truncation) untested | Medium | Phase 2 cat. 8 + edge set |
| W12 | tool_calls-path vs JSON-path not separated | Low | Phase 2 (record path per attempt) |

---

# Deliverable 2 — Benchmark v2 Design (120–300 cases)

## 2.1 Goals

1. Enough samples per category (target **≥10**, ideally 15–20) that a one-sample flake does
   not flip a category.
2. **Argument-level scoring**, not just tool-name matching.
3. Repeatable generation so the suite can grow without hand-authoring every case.
4. Bilingual (English + Korean) coverage matching the product.

**Target size:** 150 cases for v2.0 (12 categories × ~12), expandable to 300. Each case run
**R≥3 times** → 450+ measurements, giving stable rates and real CIs.

## 2.2 Case schema (extends `BenchmarkPrompt`)

The current `BenchmarkPrompt` only has `case_id`, `prompt`, `expected_tool`, `notes`. v2
adds structured expectations so arguments and behavior can be graded:

```python
@dataclass(frozen=True)
class BenchmarkCaseV2:
    case_id: str
    category: str                       # one of the 12 categories below
    lang: str                           # "en" | "ko" | "mixed"
    prompt: str
    expected_tool: str | None           # None = expect no tool (negative control)
    expected_args: dict[str, Any] | None = None   # exact/required arg values
    arg_match: str = "subset"           # "exact" | "subset" | "ignore"
    accept_alternatives: tuple[str, ...] = ()      # tools also acceptable (disambiguation)
    expect_clarification: bool = False  # good behavior = ask, not act
    difficulty: str = "normal"          # "easy" | "normal" | "hard"
    notes: str = ""
```

`expected_args` + `arg_match` is the W3 fix. Scoring becomes a tuple:
`(tool_correct, args_correct, json_ok, schema_ok)`.

## 2.3 The 12 categories

For each: **Purpose · Example prompts · Success criteria · Expected tool behavior.** Real
tools/params taken from [contracts.py](../../web/services/chatbot-backend/app/tools/contracts.py).

### 1. Positive tool invocation
- **Purpose:** baseline — unambiguous single-tool requests fire the right tool with right args.
- **Examples:** "Stop the simulation." · "Inspect station 4." · "Pause the run." ·
  "시뮬레이션 정지해줘."
- **Success:** `tool == expected` AND required args present & correct AND valid JSON+schema.
- **Expected behavior:** exactly one tool call, no extra args.

### 2. Negative control prompts
- **Purpose:** model must **not** invent a tool for non-actionable input.
- **Examples:** "What is the current process status?" · "What can you do?" · "Hi there." ·
  "How does the AGV cell work?" · "현재 상태 어때?"
- **Success:** `tool is None` (no tool fired).
- **Expected behavior:** decline / answer conversationally; **no** tool call. Expanded from
  3 → ~15 cases incl. greetings, meta, info queries, out-of-domain.

### 3. Ambiguous commands
- **Purpose:** under-specified intent — measure decline-vs-clarify-vs-guess.
- **Examples:** "Can you handle that one over there?" · "Do the thing." · "Start it." (start
  what?) · "저거 처리해줘."
- **Success:** `tool is None` **or** `expect_clarification` satisfied; guessing a specific
  station/tool is a failure.
- **Expected behavior:** prefer clarification; never fabricate a `station_id`.

### 4. Parameter extraction (single)
- **Purpose:** correct extraction of one parameter.
- **Examples:** "Move the AGV to station 7." → `move_to_station{station_id:7}` · "Set speed
  to 2x." → `set_sim_speed{speed_multiplier:2.0}` · "스테이션 3 검사해."
- **Success:** tool correct AND the one arg value exactly correct (`arg_match:"exact"`).
- **Expected behavior:** integer station, float multiplier, correct types.

### 5. Multi-parameter extraction
- **Purpose:** extract 2–4 params into one call.
- **Examples:** "Start a sim with 5 AGVs at 1.5x speed named NightShift." →
  `start_simulation{agv_count:5, speed_multiplier:1.5, simulation_name:"NightShift"}` ·
  "Run the task at station 2 with high priority." → `run_station_task{station_id:2, priority:"high"}`
- **Success:** all expected args correct (`arg_match:"subset"` so defaults don't penalize).
- **Expected behavior:** no dropped or swapped params; enums respected (`priority∈{normal,high}`).

### 6. Missing-parameter handling
- **Purpose:** required param absent from the request.
- **Examples:** "Move the AGV." (no station) · "Run the task." (no station) · "Set the speed."
  (no value) · "스테이션 검사해." (no number)
- **Success:** `tool is None` OR clarification; **failure** = firing with a hallucinated
  `station_id`/`speed_multiplier`, OR firing with required arg missing (schema should reject).
- **Expected behavior:** ask for the missing value, don't invent it.

### 7. Long natural-language requests
- **Purpose:** robustness to verbose, noisy phrasing burying a single intent.
- **Examples:** a 3–4 sentence operator narrative ("We had a rough morning shift, throughput
  dipped, anyway can you just go ahead and restart the simulation with the usual three AGVs")
  → `start_simulation{agv_count:3}`.
- **Success:** correct tool + args despite filler; no distraction by irrelevant numbers.
- **Expected behavior:** ignore non-parameter numbers/noise.

### 8. Structured KPI / acceptance requirements
- **Purpose:** the hard nested-array case — `acceptance[]` extraction (Phase-1's only miss).
- **Examples:** "Start with 4 AGVs and accept only if throughput ≥ 70/h, avg wait < 12s, and
  zero collisions." · Korean: "처리량 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이면 통과로
  4대 돌려줘."
- **Success:** `start_simulation` with `acceptance` array whose items have correct
  `metric`/`comparator`/`threshold` (metric ∈ enum). `arg_match:"subset"`.
- **Expected behavior:** map NL → structured criteria; this is where fine-tuning (Phase 3)
  is most likely to help.

### 9. Invalid parameter values
- **Purpose:** out-of-range / wrong-type values.
- **Examples:** "Move to station -1." · "Set speed to 0." / "to -2x." · "Start with 'five'
  AGVs." · "Inspect station 999." (nonexistent)
- **Success:** schema/validator rejects (→ repair or decline), OR clamps per a documented
  rule. **Failure** = silently passing an invalid value downstream.
- **Expected behavior:** surface invalid input; defines whether validation layer should add
  range checks (currently it does not — see Phase 2 findings hook).

### 10. Tool disambiguation
- **Purpose:** same target, different verb → different tool (`run` vs `move` vs `inspect`).
- **Examples:** "Go to station 3." (move) vs "Work station 3." (run) vs "Check station 3."
  (inspect) — identical `station_id`, different tool.
- **Success:** exact tool; `accept_alternatives` empty (these *are* distinct).
- **Expected behavior:** verb sensitivity; this is where Phase-1 Ollama erred
  (`run_station_task` → `inspect_station`).

### 11. Sequential workflow requests
- **Purpose:** multi-step intent in one utterance.
- **Examples:** "Move to station 2, then run the task there." · "Pause it, then set speed to
  0.5x." · "Start a sim and then stop it after." (intent ordering)
- **Success:** at minimum the **first** actionable tool is correct; document whether the
  architecture supports queuing (today `propose_tool_call` returns one `ToolCall`). Flag
  multi-tool as a known single-call limitation.
- **Expected behavior:** pick the correct first action; note the rest for product backlog.

### 12. State-dependent requests
- **Purpose:** correctness depends on simulation state (passed via `station`/context).
- **Examples:** "Resume." with nothing paused · "Stop." with nothing running · "Pause." mid-run.
- **Success:** correct tool given provided state context; the harness must pass a state object
  (extend the `station`/context arg). Scored against state-aware expectation.
- **Expected behavior:** the model proposes; the application layer enforces legality. Tests
  whether the model at least proposes the *coherent* lifecycle command.

## 2.4 Scoring model (v2)

Per case, per repeat, record:

| Field | Source |
|---|---|
| `tool_correct` | `actual_tool ∈ {expected_tool} ∪ accept_alternatives` (or both None) |
| `args_correct` | `expected_args` compared per `arg_match` (new) |
| `json_parse_success` | as today (`_json_parse_succeeded`) |
| `schema_validation_success` | as today (LLM attempt `valid:true`) |
| `repair_retry_used` | `len(attempts) > 1` |
| `rule_based_fallback_used` | tool returned but no LLM attempt valid |
| `clarification_appropriate` | for ambiguous/missing: did it decline/ask? |
| `latency_ms`, `attempt_count`, `output_path` | timing + which extraction branch |

**Aggregate:** report each rate **with a 95% Wilson CI** and **per category**. Add a headline
**Task Success Rate = tool_correct AND args_correct AND (schema_ok OR acceptable_fallback)** —
the metric that actually reflects "did the agent do the right thing."

## 2.5 Generation strategy (so cases are easy to add)

Three layers, ordered by effort:

1. **Template + slot expansion (primary).** YAML/JSONL templates per category with slots:
   ```yaml
   - category: parameter_extraction
     template: "Move the AGV to station {station}."
     tool: move_to_station
     args: { station_id: "{station}" }
     slots: { station: [1,2,3,7,12] }
     lang: en
   ```
   A generator expands the cross-product into concrete `BenchmarkCaseV2` rows. Adding a
   category or a slot value adds many cases with one edit. **Cheap, deterministic, reviewable.**
2. **Paraphrase augmentation (secondary).** Use a *larger* model (offline, one-time) to
   paraphrase each seed into 2–3 surface variants (formal/informal/typo/Korean). Human-review
   a sample; store as static JSONL so the benchmark stays reproducible (never generate at
   run time).
3. **Production harvest (tertiary, ongoing).** Log real chat → tool decisions behind a flag,
   hand-label a weekly sample, promote interesting failures into the static suite. This keeps
   the benchmark aligned with real usage drift.

Suite lives as **static, version-controlled JSONL** (`docs/benchmark/cases/v2/*.jsonl`) so
runs are reproducible. Generators are scripts that *emit* JSONL; the committed JSONL is the
source of truth for any published result.

---

# Deliverable 3 — Phase 2: Validation-Layer Benchmark

## 3.1 Question

Phase 1 conflates two things: the **raw model** and the **validation layer wrapped around
it** (JSON extraction → schema validation → repair retry → deterministic rule-based
fallback). Phase 2 isolates the validation layer's contribution via a **2×2 ablation**:

| | Provider only | Provider + Validation Layer |
|---|---|---|
| **Ollama** | A1 | A2 |
| **llama.cpp** | B1 | B2 |

- **A1/B1 (provider only):** single LLM call, parse the raw output, **no** repair retry,
  **no** rule-based fallback. If it doesn't produce valid schema-conformant JSON on the first
  shot, it fails. This is the model's *intrinsic* structured-output ability.
- **A2/B2 (production stack):** the full path in `propose_tool_call` — JSON extraction +
  repair (`structured_retry_count`) + `build_rule_based_tool_call` fallback.

**The validation layer logic must be byte-identical for both providers.** It already is —
`LlamaCppLlmGateway` subclasses `OllamaLlmGateway` and only overrides `_post_chat` transport.
Phase 2 must *guarantee* this stays true by routing both through the same validation module
and asserting identical config (`structured_retry_count`, schema, fallback, normalization).

## 3.2 Isolating the layer

Add a **toggle** so the same gateway can run with validation **off** (A1/B1) or **on**
(A2/B2). Concretely, parameterize:

- `structured_retry_count = 0` → disables repair retry.
- `enable_rule_based_fallback = False` → `propose_tool_call` returns `None` instead of
  `build_rule_based_tool_call(...)`.
- `enable_argument_normalization` → toggles a (new, optional) normalization step.

This makes the layer an **ablatable** wrapper rather than baked-in, which is also good
production hygiene.

## 3.3 Validation layer — components measured

| Component | Where today | Measured effect |
|---|---|---|
| JSON extraction (fenced/loose) | `_parse_json_content` (regex fallback) | % rescued from non-JSON |
| Schema validation | `ToolRouter.validate` + pydantic contracts | % caught before dispatch |
| Schema retry (repair) | loop in `propose_tool_call` | % recovered on attempt 2 |
| Argument normalization | *not yet present* — propose adding | % args fixed (e.g. "3"→3) |
| Deterministic fallback | `build_rule_based_tool_call` | % salvaged when LLM fails |

## 3.4 Metrics (per cell A1/A2/B1/B2)

**Primary (the ablation payoff):**
- **Task Success Rate** (tool+args+valid) — *the* headline.
- **Valid-output rate** (schema-conformant tool call eventually produced).
- **Δ from validation layer** = (A2 − A1) and (B2 − B1), with CIs. This is the deliverable.

**Diagnostic / additional measurements:**
- First-attempt schema success (A1/B1 intrinsic).
- Repair-retry **trigger rate** and **repair success rate** (of retries, how many recover).
- Rule-based **fallback rate** and **fallback correctness** (when it fires, is it right?).
- **Fallback masking rate** — cases the model got wrong but fallback *also* got wrong (layer
  can't save a bad intent).
- Argument-correctness rate (separate from tool-name).
- Per-category breakdown (which categories the layer rescues — expect KPI/missing-param).

**Latency (the layer's cost):**
- Added latency from repair retries: `latency(A2) − latency(A1)` per case; report mean and
  the **conditional** cost (latency *given* a retry fired ≈ 2× a single call).
- p50/p95/p99 for each cell, **including** a concurrency profile (4–8 concurrent).
- Fallback latency (near-zero, deterministic) vs LLM-call latency.

## 3.5 Experimental controls (fairness & reproducibility)

- **Same GGUF, same params** both providers (already true: identical blob, `num_ctx 2048`,
  matching `num_predict`). Pin and record server flags (`-ngl 99`, temperature, seed where
  supported).
- **Fixed seeds** where the runtime allows; otherwise **R≥5 repeats** per case and report
  mean ± CI. Local sampling is the dominant noise source — repetition is mandatory.
- **Warm-up excluded / reported separately** (first-request already separated in harness).
- **Randomized prompt order** per repeat to avoid cache-ordering bias; record order.
- **Identical prompt templates** (`PromptTemplateStore`) for both providers.
- **Same hardware, no contention** — one provider served at a time; log VRAM/driver/CUDA
  (already in README). Note: Ollama keep-alive vs llama.cpp resident model affects cold start
  — report cold/warm separately, never blended.
- **Pre-registration:** freeze the v2 case suite + metric definitions + hypotheses *before*
  running, to avoid p-hacking the categories.

## 3.6 Reporting format

Reuse the harness output path (`write_benchmark_outputs`) extended with the new fields, plus
a generated markdown report `docs/benchmark/raw/phase2_validation_ablation.md`:

1. **2×2 headline table** — Task Success Rate per cell with CIs.
2. **Δ-validation table** — per provider, the lift each layer component adds (waterfall:
   raw → +extraction → +retry → +fallback).
3. **Per-category matrix** — 12 categories × 4 cells.
4. **Latency table** — p50/p95/p99 per cell + retry cost + concurrency profile.
5. **Failure gallery** — N worst cases per cell with the raw model output (for the portfolio
   write-up).
6. Raw JSON + CSV (machine-readable, as today).

## 3.7 What Phase 2 decides — and what it *did* decide (2026-06-11)

The pre-registered decision rule was:

- If **A2/B2 ≈ A1/B1** (layer adds little) → the base model is already good enough; **skip
  fine-tuning**, invest in prompt/schema.
- If **A2/B2 ≫ A1/B1** and the lift is mostly **fallback** (not model) → the product is
  carried by deterministic code; document it honestly, and fine-tuning could let us *retire*
  fallback (a great portfolio story).
- If **first-attempt schema success is low even in A1/B1** and fallback can't cover the hard
  categories (KPI, multi-param) → **fine-tuning is justified** → Phase 3.

### Actual Phase 2-B outcome (which branch fired)

**The first branch fired on Ollama** (A1 75.6% ≈ A2 75.9%, fully overlapping CIs) and the
layer added a small, real lift on llama.cpp (B1 69.0% → B2 74.0%). The lift is **not** mostly
fallback — fallback fire rate collapsed to 1.5% and the gain comes from the repair retry
(repair success 52–60%). And the **format** premise of the third branch is dead: with the
fixes in, JSON parse is **100%** and first-pass schema validity is **94%** on both ON cells.

**Consequence for the Phase-3 gate.** The third branch — "first-attempt schema success is
low" — is the condition §4.1 was written to test, and it is now **false**. Read literally,
the original gate says *do not fine-tune.* What keeps Phase 3 alive is a **different**,
narrower fact the gate did not anticipate: two categories fail for reasons the layer is
provably blind to, and those reasons are **semantic, not format**:

| Residual (layer-immune) | Ollama | llama.cpp | Why the layer can't help |
|---|---|---|---|
| `kpi_acceptance` (nested `acceptance[]`) | **18–22%** | 60% | valid JSON, *wrong/empty* criteria — schema passes |
| `disambiguation` (verb→tool) | **60%** (A1=A2) | 80% | valid tool call, *wrong tool* — retry can't know |

So the decision is: **Phase 3 is conditionally GO, but re-scoped from "teach JSON/schema"
to "teach semantics," with new metrics** (§4.1 / §4.5 revised). And before paying for it,
run the §3.8 diagnostic — because the same GGUF blob scores 3× differently on
`kpi_acceptance` across serving regimes, which means part of the "model limitation" may be a
free serving/prompt win, not something SFT must buy.

## 3.8 Phase 2.5 — pre-SFT semantic diagnostic *(EXECUTED 2026-06-11 — see [PHASE25_DIAGNOSTIC.md](PHASE25_DIAGNOSTIC.md))*

> **Result (prompt lever, Ollama, layer ON, R=5):** `kpi_acceptance` **20.0% → 92.0%**
> (+72 pp, non-overlapping CIs) — it was a **prompt-omission artifact** (the shipped
> prompt never named the `acceptance` array), **not** a model limit → **dropped from
> Phase 3.** `disambiguation` **58.3% → 60.0%** (overlapping CIs) — the model ignores an
> explicit verb→tool instruction (run/move collapse to `inspect_station`) → **the sole
> surviving SFT candidate.** Caveat logged: a heavier prompt with inline JSON exemplars
> collapsed both categories to 0% (2B model emits empty/decline) — keep prompts compact.
> Serving lever still untried: PHASE2B shows `disambiguation` is 80% on reasoning-off
> llama.cpp vs 60% on Ollama (same blob), so step 2 below may close it for free.
>
> **[x] Enriched prompt SHIPPED (2026-06-11).** Promoted `templates_phase25/` →
> shipped `templates/tool_planning_system.txt` (now byte-identical) and re-ran the full
> 133-case suite (A2, R=5). `kpi_acceptance` **22→94%** (CI-separated), **no other
> category regressed beyond CI overlap**, overall **75.9→77.1%**. Gate passed → shipped.
> See the *Full-suite regression confirmation* section of PHASE25_DIAGNOSTIC.md
> (raw: `raw/phase25_full_regression/`).

**Goal:** establish the *true, best-achievable* baseline on the two Phase-3 target categories
with zero training, so Phase 3 is graded against the best prompt+serving — not the worst —
and so we don't fine-tune away a gap that a prompt change closes for free.

**Motivating evidence (PHASE2B per-category, identical `sha256-b709d815…` blob):**

| Category | Ollama (`think:false`) | llama.cpp (reasoning-off) | Δ on identical weights |
|---|---|---|---|
| `kpi_acceptance` | 18–22% | 60% | **+38 pp** from serving regime alone |
| `disambiguation` | 60% | 80% | +20 pp |
| `missing_parameter` | 63% | 15% | −48 pp (regime cuts the *other* way) |

A 3× swing on the same weights is a serving/decoding/prompt artifact, not intrinsic
capability. SFT (5–8 days) must not be commissioned until these cheap levers are exhausted.

**Experiments (≈1 day, no training):**
1. **Serving parity.** Re-run `kpi_acceptance` + `disambiguation` on Ollama under the same
   reasoning-off decode path llama.cpp used; quantify how much of the A/B gap is regime.
2. **Prompt / few-shot.** Add 2–3 in-context `acceptance[]` exemplars and explicit
   verb→tool guidance to the tool-planning prompt; re-measure (layer ON, R≥5, CIs).
3. **Decision rule:**
   - If prompt+serving lifts `kpi_acceptance` to ≳60–70% and `disambiguation` to ≳80% →
     **Phase 3 is not justified for production**; do it only as a labelled portfolio piece
     (§6), or drop it.
   - If a material residual survives the best prompt+serving (expected: `kpi_acceptance`
     still well below target) → **proceed to Phase 3**, scoped to that residual, graded
     against this new best baseline.

**Deliverable:** a short addendum to PHASE2B (`kpi_acceptance`/`disambiguation` under
best prompt+serving, with CIs) that becomes the Phase-3 control (C-cell) baseline.

---

# Deliverable 4 — Phase 3: Fine-Tuning Benchmark

## 4.1 Is fine-tuning justified? — gate REVISED after Phase 2-B

**Original gate (format-bottleneck framing) — now INVALIDATED by Phase 2-B.** It read:
fine-tune only if (1) first-attempt schema/JSON success < ~75%, (2) the layer can't cheaply
close it, (3) the failures are *learnable structure/format* issues. Phase 2-B killed
criterion (1): the fixed layer yields **100% JSON parse, 94% first-pass schema validity**.
The format problem this gate was guarding against **no longer exists**, so by the *letter*
of the original gate, Phase 3 is NOT justified.

**Revised gate (semantic-residual framing) — what actually keeps Phase 3 alive.** Fine-tune
**only if**, after the §3.8 best-prompt+serving diagnostic:

1. A category fails on **semantics, not format** — the model emits *valid, schema-conformant*
   JSON that is *wrong* (empty/incorrect `acceptance[]`; wrong verb→tool). The validation
   layer is provably blind to these (a retry can't know a valid call is semantically wrong;
   `disambiguation` is A1=A2), **and**
2. The residual **survives** the §3.8 cheap levers (serving parity + few-shot), i.e. it is
   not a free prompt/serving win, **and**
3. The residual is **learnable from examples** — NL→nested-criteria mapping and verb→tool
   selection are exactly what task-specific SFT improves.

**Candidates after §3.8 ran (2026-06-11) — criterion (2) now resolved:**

| Candidate | (1) semantic? | (2) survives §3.8 prompt lever? | Verdict |
|---|---|---|---|
| `kpi_acceptance` | yes | **NO** — prompt lifts 20%→92% (+72 pp) | **dropped** (ship prompt, not SFT) |
| `disambiguation` | yes | **YES** — 58%→60%, unmoved | **sole surviving candidate** |
| `multi_parameter` | — | — (100% on all four cells) | dropped at 2-B |

So Phase 3, if it runs at all, is **`disambiguation` only** — and is further gated behind
the untried serving lever (reasoning-off llama.cpp scored it 80% vs Ollama 60% on the same
blob; see PHASE2B). Confirm that doesn't close it before training.

Because overall task success is already ~76% and the layer carries it, **Phase 3 is no longer
a production necessity** — it is a targeted lift on two layer-immune categories. If §3.8
closes them, Phase 3 becomes a **deliberate portfolio artifact** (see Deliverable 6); label
the motivation explicitly rather than pretending it's a production fix.

## 4.2 Method & dataset size

- **Method:** **LoRA / QLoRA SFT** on `qwen3.5:2b` (small base, single 8 GB GPU — full FT is
  unnecessary and risky). Target the structured tool-call task only; do **not** try to make a
  general chat model.
- **Size estimate:** structured-output SFT on a *narrow* schema (9 tools, ~5 params) is
  data-efficient. Rough targets:
  - **Minimum useful:** ~500–800 examples.
  - **Comfortable:** **1,500–3,000** examples.
  - **Diminishing returns** past ~5k for this narrow a task.
  Distribution should **mirror the 12 categories**, over-weighting the hard ones (KPI,
  multi-param, missing-param, disambiguation) since those drive the loss. Include **negative
  controls** (target = "no tool / clarify") so the model learns to *not* fire — otherwise SFT
  makes it trigger-happy.

## 4.3 Training dataset format

Instruction/response pairs matching the *production* prompt template + the schema, so the
fine-tuned model fits the existing `propose_tool_call` path with no prompt change:

```jsonl
{"messages":[
  {"role":"system","content":"<tool_planning_system rendered>"},
  {"role":"user","content":"<tool_planning_user: user_message + station_context>"},
  {"role":"assistant","content":"{\"name\":\"move_to_station\",\"arguments\":{\"station_id\":7}}"}
]}
```

- Target is **exactly** the JSON the gateway expects (`ToolCallDecision`/`ToolCall` shape).
- Negative/ambiguous cases → assistant emits the agreed "no tool" sentinel (e.g.
  `{"name": null}` or a clarification object) — define one canonical form.
- Include **bilingual** (en/ko) inputs.
- **Provenance per example:** `template | paraphrase | harvested` for auditability.

**Sources:** (a) the Phase-2 template generator (gold labels are known), (b) paraphrase
augmentation, (c) harvested + corrected production cases. Gold JSON is *constructed*, never
scraped from the weak model.

## 4.4 Train / validation / test split

- **Critical rule: split by template/intent family, not by row**, to prevent leakage (a
  paraphrase of a train prompt must not appear in test).
- **Train 70% / Val 15% / Test 15%**, stratified by category and language.
- **Held-out generalization set:** the **Phase-2 v2 suite is the test set** — the model must
  **never** see Phase-2 cases (or their paraphrases) in training. This keeps base-vs-finetuned
  comparison honest and on the exact same yardstick.
- Val set used only for early-stopping / LoRA hyperparameter choice.

## 4.5 Benchmark methodology & base-vs-fine-tuned protocol

Run the **identical Phase-2 harness** on the held-out v2 test set for:

| Model | Validation layer | Cell |
|---|---|---|
| Base `qwen3.5:2b` | off | C1 |
| Base `qwen3.5:2b` | on | C2 |
| Fine-tuned | off | D1 |
| Fine-tuned | on | D2 |

Served identically (same Ollama/llama.cpp runtime, same flags, same prompts, R≥5 repeats,
CIs). The **headline comparison is D1 vs C1** (intrinsic improvement) and **D2 vs C2**
(production improvement).

**Metrics (all vs base, with CIs) — headline shifted from format to semantics after 2-B:**
- **Per-category Task Success (tool+args) on `kpi_acceptance` and `disambiguation` ↑** — the
  new headline. These are the only categories Phase 3 targets.
- **Argument correctness ↑** specifically on the nested `acceptance[]` structure (correct
  `metric`/`comparator`/`threshold` items), and **verb→tool accuracy ↑** on `disambiguation`.
- JSON parse / schema validation success — **already saturated (100% / 94%) with the layer
  ON, so these are regression guards, not lift metrics.** SFT must not *drop* them.
- **Repair-retry rate ↓** (fewer second calls → latency win); **fallback rate** already ~1.5%.
- Latency impact: per-token speed ~unchanged (same arch + small LoRA); end-to-end should
  *improve* via fewer retries — report raw and effective.
- **Regression check (critical):** the 100%-solved categories (`positive_invocation`,
  `parameter_extraction`, `multi_parameter`, `long_request`) and negative-control /
  `missing_parameter` decline behavior must **not** regress — SFT on two hard categories
  must not make the model trigger-happy or break what the layer already solved.

**Success criteria for "fine-tuning worked" (REVISED):** D-cell **Task Success on
`kpi_acceptance` + `disambiguation`** materially exceeds the **§3.8 best-prompt+serving
baseline** (not the raw Phase-2-B number) with non-overlapping CIs; schema/JSON validity
holds at ≥94/100%; and **no** regression on the solved categories, negative controls, or
latency. (Note: the old "D1 first-attempt schema ≫ C1" criterion is retired — schema is
already 94%, so there is no headroom there to win.)

---

# Deliverable 5 — Experimental Roadmap

### Phase 1 — Provider Benchmark *(completed)*
- **Goal:** stand up the harness; smoke-compare Ollama vs llama.cpp on the tool path.
- **Deliverables:** harness, 12-prompt run, GPU fix, [README.md](README.md).
- **Success criteria:** ✅ reproducible run, both providers measured, latency gap root-caused
  (CPU-only build → CUDA).
- **Effort:** done.
- **Portfolio value:** **Medium.** Strong systems-debugging story (CPU/GPU build root-cause,
  GGUF loader patches). Weak as an *evaluation* (n=12).

### Phase 2 — Validation-Layer Benchmark *(completed 2026-06-11)*
- **Goal:** statistically credible v2 suite (133 cases, R=5, CIs, arg-level scoring);
  isolate the validation layer via 2×2 ablation with identical logic per provider.
- **Deliverables:** ✅ v2 JSONL suite (133 cases, 12 cats, en+ko) + generator;
  `BenchmarkCaseV2` + arg scoring; ablation toggles; 2×2 + Δ-validation + per-category +
  latency report; the two layer fixes (decline retry + range validation).
- **Outcome:** ✅ **Phase 2-B PASS** — fixed layer net-neutral on Ollama, +5 pp on
  llama.cpp (non-overlapping CIs); A2 regression repaired (54.3 → 75.9). See
  [PHASE2B_FULL_RESULTS.md](PHASE2B_FULL_RESULTS.md). The layer was **more than sufficient**
  — refuting the working hypothesis and invalidating the format-based Phase-3 gate.
- **Portfolio value:** **High.** Rigorous eval design, ablation, CIs, and a clean
  "found-and-fixed my own −21 pp regression" story.

### Phase 2.5 — Pre-SFT Semantic Diagnostic *(EXECUTED 2026-06-11 — see [PHASE25_DIAGNOSTIC.md](PHASE25_DIAGNOSTIC.md))*
- **Goal:** establish the best-achievable, zero-training baseline on `kpi_acceptance` +
  `disambiguation` so Phase 3 isn't fine-tuning away a free prompt/serving win. See §3.8.
- **Outcome:** ✅ prompt lever (Ollama, layer ON, R=5): **`kpi_acceptance` 20%→92%**
  (+72 pp, non-overlapping CIs) — prompt-omission artifact, **dropped from Phase 3**;
  **`disambiguation` 58%→60%** (overlapping) — instruction-resistant, **sole survivor**.
  Logged a 2B prompt-fragility finding (inline JSON exemplars → 0% collapse).
  **Enriched prompt SHIPPED 2026-06-11** after a full 133-case regression re-run
  (A2, R=5): `kpi_acceptance` **22→94%**, no other category regressed beyond CI overlap,
  overall **75.9→77.1%**. The shipped `templates/tool_planning_system.txt` is now
  byte-identical to `templates_phase25/`.
- **Effort:** ~½ day, no training.
- **Portfolio value:** **High.** "A 3-line prompt fix beat the case for fine-tuning on one
  of two targets; I isolated it before spending a week on SFT" is a strong judgment story.

### Phase 3 — Fine-Tuning *(conditional — `disambiguation` only, serving lever first)*
- **Goal:** *only if `disambiguation` survives the §3.8 step-2 serving lever*, LoRA-SFT
  `qwen3.5:2b` for **verb→tool selection** (run/move/inspect). NOT JSON/schema (94/100%
  via layer); NOT `kpi_acceptance` (closed by prompt); `multi_parameter` dropped (100%).
- **Pre-req before any training:** re-measure `disambiguation` with the enriched prompt on
  reasoning-off llama.cpp 9559 (PHASE2B: 80% there vs 60% Ollama on the same blob). If it
  lands ~80%, **Phase 3 is unnecessary** — switch serving instead.
- **Deliverables:** dataset over-weighting verb-disambiguation triples (+ negative controls
  + the solved categories as anti-regression ballast), leak-safe split, LoRA config, GGUF
  export, base-vs-finetuned report.
- **Success criteria:** D-cell `disambiguation` Task Success ≫ the §3.8 best-prompt+serving
  baseline (non-overlapping CIs); schema/JSON hold ≥94/100%; **no** regression on the
  solved categories, negative controls, or latency. (Old "schema ≫" criterion retired.)
- **Effort:** **~4–6 days** (dataset ~1.5–2d, training+iteration ~2d, eval+writeup ~1–2d).
- **Portfolio value:** **Medium–High.** A single-category SFT lift is a tidy story; but the
  stronger narrative is now "validation layer + a 3-line prompt + serving choice solved
  almost everything — fine-tuning was scoped down to one verb-sensitivity edge, here's the
  cost-benefit," which is a more senior, more honest finding than a big SFT number.

---

# Deliverable 6 — Portfolio Impact Assessment

## 6.1 Are Phase 2 / Phase 3 likely to produce measurable improvements?

- **Phase 2 (very likely to produce reportable results).** Even with no code change to the
  agent, the *measurement* improves: CIs, arg-scoring, and the ablation will produce concrete,
  defensible numbers. The validation layer almost certainly shows a real lift (Phase-1 already
  hints: llama.cpp needed fallback on `set_speed`; KPI failed for both). Phase 2 *will* yield
  a quantified "validation layer adds +X% task success at +Y ms" headline — that is the
  deliverable regardless of which way it breaks.
- **Phase 3 (conditionally likely).** Narrow structured-output SFT on a small model reliably
  moves first-attempt JSON/schema success and enum/arg adherence. The risk is not "no
  improvement" but "the validation layer already covered it," making the *production* delta
  small even if the *intrinsic* (layer-off) delta is large. Frame it as intrinsic-vs-net.

## 6.2 Which metrics most likely improve, and by how much (rough, hypothesis)

| Metric | Phase 2 (layer on vs off) | Phase 3 (finetuned vs base, layer off) |
|---|---|---|
| First-attempt JSON parse success | n/a (defines A1) | **+10–25 pp** (e.g. 60%→80%+) |
| First-attempt schema success | n/a | **+15–30 pp** on hard categories |
| Task success (tool+args) | **+15–40 pp** vs raw provider | **+10–20 pp** intrinsic |
| Repair-retry rate | (layer enables it) | **−30–60% relative** (fewer needed) |
| Rule-based fallback rate | (layer enables it) | **−40–70% relative** |
| Avg effective latency | +X ms (retry cost) | **−5–15%** (fewer retries) |
| Negative-control correctness | layer-neutral | must hold (regression guard) |

These are **pre-registered hypotheses**, not promises; the point of the design is to measure
them honestly with CIs.

## 6.3 What's most impressive to hiring managers

| Role | Most impressive result | Why |
|---|---|---|
| **AI Engineer** | The **2×2 ablation isolating the validation layer** + latency/quality trade-off curve | Shows you reason about *systems*, not just model scores; product-eng judgment. |
| **LLM Engineer** | **Phase 3 base-vs-finetuned** with leak-safe splits, CIs, and a regression guard on over-firing | Demonstrates real SFT competence and eval hygiene (the leakage + negative-control guard are senior signals). |
| **Agent Engineer** | **Argument-level + tool-disambiguation + missing-param/clarify** results, and "model proposes, system enforces" framing | These are exactly the failure modes that break real agents; shows you've productionized tool-calling. |
| **Applied AI Engineer** | The honest **"validation layer beats / complements fine-tuning, here's the cost-benefit"** narrative + the CPU→GPU root-cause | End-to-end ownership: debugging, eval, shipping decision under constraints. |

**Cross-cutting wins to foreground:** confidence intervals (you don't over-claim from n=12),
the GGUF-loader/CUDA root-cause (deep systems debugging), bilingual eval (real product), and
a **decision** ("we did/didn't fine-tune because the data said so"). The *judgment* narrative
is more impressive than any single accuracy number.

## 6.4 Recommendation

1. **Do Phase 2.** High value, modest effort, de-risks everything, produces publishable
   numbers no matter the outcome.
2. **Gate Phase 3 on Phase 2's go/no-go.** If the validation layer already hits ~95% task
   success at acceptable latency, do Phase 3 *only* as a deliberate portfolio piece and label
   it as such. If first-attempt success is the real bottleneck, Phase 3 is the strongest
   single portfolio item available here.
```
