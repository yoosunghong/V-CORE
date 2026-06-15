# Phase 2 — Validation-Layer Ablation (v2 benchmark)

Generated: 2026-06-11T08:10:45+00:00

Suite: **133 cases** across 12 categories · **R=5 repeats** · model `qwen3.5:2b`.

Cells: **A1/A2** = Ollama validation layer off/on · **B1/B2** = llama.cpp off/on. *off* = single LLM call, no repair retry, no rule-based fallback (intrinsic structured-output ability). *on* = full `propose_tool_call` path (repair retry + deterministic fallback). Rates carry Wilson 95% CIs.

## 1. Headline — Task Success Rate (tool + args correct)

| Provider | Layer OFF | Layer ON |
|---|---|---|
| Ollama | — | 77.1% [74–80] (n=665) |

## 2. Validation-layer lift (ON − OFF)

| Provider | Task success Δ | Schema-valid Δ | Tool-correct Δ |
|---|---|---|---|

## 3. Per-cell diagnostic rates

| Metric | A2 |
|---|---|
| Task success | 77.1% |
| Tool correct | 77.4% |
| Args correct | 77.1% |
| JSON parse | 100.0% |
| Schema valid (1st-pass LLM) | 93.5% |
| Repair-retry rate | 7.4% |
| Rule-based fallback rate | 1.5% |
| Clarification appropriate | 58.3% |

Fallback correctness / repair success (of the cases that triggered them):

| Diagnostic | A2 |
|---|---|
| Fallback correctness | 0.0% |
| Repair success | 67.3% |

## 4. Per-category task success

| Category | A2 |
|---|---|
| positive_invocation | 92.9% |
| negative_control | 67.1% |
| ambiguous | 64.0% |
| parameter_extraction | 100.0% |
| multi_parameter | 100.0% |
| missing_parameter | 41.7% |
| long_request | 100.0% |
| kpi_acceptance | 94.0% |
| invalid_parameter | 60.0% |
| disambiguation | 63.3% |
| sequential | 90.0% |
| state_dependent | 58.0% |

## 5. Latency (ms)

| Cell | mean | p50 | p95 | p99 | mean w/ retry | mean w/o retry |
|---|---|---|---|---|---|---|
| A2 | 2123 | 1734 | 3500 | 9629 | 3063 | 2049 |

## 6. Per-language task success

| Lang | A2 |
|---|---|
| en | 79.2% |
| ko | 74.7% |

## 7. Failure gallery

### A2

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| ambiguous_ko_009 | ko | — | inspect_station | json_content | 알아서 해줘. |
| invalid_parameter_en_003 | en | — | set_sim_speed | rule_based_fallback | Set the speed to -2x. |
| state_dependent_en_004 | en | resume_simulation | — | json_content | Pick it back up where we left off. |
| ambiguous_ko_007 | ko | — | inspect_station | json_content | 저거 처리해줘. |
| positive_invocation_ko_010 | ko | resume_simulation | pause_simulation | json_content | 시뮬레이션 재개해줘. |
| invalid_parameter_ko_008 | ko | — | move_to_station | json_content | AGV '다섯'대로 시작해. |
| missing_parameter_en_004 | en | — | inspect_station | json_content | Inspect the station. |

---

Raw machine-readable results: `phase2_validation_ablation.json` / `phase2_validation_ablation.csv` in this directory.
