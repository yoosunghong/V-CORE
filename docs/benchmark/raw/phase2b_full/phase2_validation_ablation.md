# Phase 2 — Validation-Layer Ablation (v2 benchmark)

Generated: 2026-06-11T06:55:18+00:00

Suite: **133 cases** across 12 categories · **R=5 repeats** · model `qwen3.5:2b`.

Cells: **A1/A2** = Ollama validation layer off/on · **B1/B2** = llama.cpp off/on. *off* = single LLM call, no repair retry, no rule-based fallback (intrinsic structured-output ability). *on* = full `propose_tool_call` path (repair retry + deterministic fallback). Rates carry Wilson 95% CIs.

## 1. Headline — Task Success Rate (tool + args correct)

| Provider | Layer OFF | Layer ON |
|---|---|---|
| Ollama | 75.6% [72–79] (n=665) | 75.9% [73–79] (n=665) |
| llama.cpp | 69.0% [65–72] (n=665) | 74.0% [71–77] (n=665) |

## 2. Validation-layer lift (ON − OFF)

| Provider | Task success Δ | Schema-valid Δ | Tool-correct Δ |
|---|---|---|---|
| Ollama | +0.3 pp | +20.3 pp | +0.0 pp |
| llama.cpp | +5.0 pp | +7.2 pp | +5.0 pp |

## 3. Per-cell diagnostic rates

| Metric | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| Task success | 75.6% | 75.9% | 69.0% | 74.0% |
| Tool correct | 79.8% | 79.8% | 72.0% | 77.0% |
| Args correct | 75.6% | 75.9% | 69.0% | 74.0% |
| JSON parse | 83.2% | 100.0% | 88.9% | 100.0% |
| Schema valid (1st-pass LLM) | 73.7% | 94.0% | 86.8% | 94.0% |
| Repair-retry rate | 0.0% | 8.9% | 0.0% | 7.5% |
| Rule-based fallback rate | 0.0% | 1.5% | 0.0% | 1.5% |
| Clarification appropriate | 65.7% | 67.0% | 33.9% | 47.8% |

Fallback correctness / repair success (of the cases that triggered them):

| Diagnostic | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| Fallback correctness | — | 0.0% | — | 0.0% |
| Repair success | — | 52.5% | — | 60.0% |

## 4. Per-category task success

| Category | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| positive_invocation | 98.6% | 100.0% | 100.0% | 100.0% |
| negative_control | 94.3% | 81.4% | 62.9% | 62.9% |
| ambiguous | 86.0% | 76.0% | 48.0% | 54.0% |
| parameter_extraction | 100.0% | 100.0% | 100.0% | 100.0% |
| multi_parameter | 100.0% | 100.0% | 100.0% | 100.0% |
| missing_parameter | 63.3% | 51.7% | 15.0% | 15.0% |
| long_request | 100.0% | 100.0% | 100.0% | 100.0% |
| kpi_acceptance | 18.0% | 22.0% | 60.0% | 60.0% |
| invalid_parameter | 8.0% | 56.0% | 2.0% | 60.0% |
| disambiguation | 60.0% | 60.0% | 80.0% | 80.0% |
| sequential | 90.0% | 90.0% | 90.0% | 90.0% |
| state_dependent | 76.0% | 68.0% | 66.0% | 68.0% |

## 5. Latency (ms)

| Cell | mean | p50 | p95 | p99 | mean w/ retry | mean w/o retry |
|---|---|---|---|---|---|---|
| A1 | 1420 | 1253 | 2175 | 2368 | — | 1420 |
| A2 | 1915 | 1685 | 3231 | 4631 | 3323 | 1777 |
| B1 | 1182 | 1070 | 1965 | 2178 | — | 1182 |
| B2 | 1288 | 1116 | 2062 | 3048 | 2290 | 1207 |

## 6. Per-language task success

| Lang | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| en | 76.2% | 79.2% | 69.0% | 73.7% |
| ko | 75.0% | 72.0% | 69.0% | 74.3% |

## 7. Failure gallery

### A1

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| invalid_parameter_en_003 | en | — | set_sim_speed | json_content | Set the speed to -2x. |
| state_dependent_en_004 | en | resume_simulation | — | none | Pick it back up where we left off. |
| invalid_parameter_ko_009 | ko | — | inspect_station | json_content | 스테이션 999 검사해. |
| kpi_acceptance_ko_005 | ko | start_simulation | — | none | 처리량 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이면 통과로 AGV 4대 돌려줘. |
| invalid_parameter_ko_008 | ko | — | move_to_station | json_content | AGV '다섯'대로 시작해. |
| negative_control_en_001 | en | — | inspect_station | json_content | What is the current process status? |
| missing_parameter_en_004 | en | — | inspect_station | json_content | Inspect the station. |

### A2

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| missing_parameter_en_002 | en | — | inspect_station | json_content | Run the task. |
| invalid_parameter_en_003 | en | — | set_sim_speed | rule_based_fallback | Set the speed to -2x. |
| state_dependent_en_004 | en | resume_simulation | — | json_content | Pick it back up where we left off. |
| negative_control_ko_012 | ko | — | inspect_station | json_content | AGV 셀이 어떻게 동작하나요? |
| kpi_acceptance_ko_005 | ko | start_simulation | — | json_content | 처리량 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이면 통과로 AGV 4대 돌려줘. |
| missing_parameter_en_004 | en | — | inspect_station | json_content | Inspect the station. |
| disambiguation_en_004 | en | run_station_task | inspect_station | json_content | Work station 10. |

### B1

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| missing_parameter_en_002 | en | — | run_station_task | json_content | Run the task. |
| invalid_parameter_en_003 | en | — | set_sim_speed | json_content | Set the speed to -2x. |
| state_dependent_en_004 | en | resume_simulation | — | none | Pick it back up where we left off. |
| negative_control_ko_012 | ko | — | run_station_task | json_content | AGV 셀이 어떻게 동작하나요? |
| missing_parameter_ko_012 | ko | — | run_station_task | json_content | 작업 좀 돌려. |
| invalid_parameter_ko_009 | ko | — | inspect_station | json_content | 스테이션 999 검사해. |
| invalid_parameter_ko_008 | ko | — | run_station_task | json_content | AGV '다섯'대로 시작해. |

### B2

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| missing_parameter_en_002 | en | — | run_station_task | json_content | Run the task. |
| invalid_parameter_en_003 | en | — | set_sim_speed | rule_based_fallback | Set the speed to -2x. |
| state_dependent_en_004 | en | resume_simulation | — | json_content | Pick it back up where we left off. |
| missing_parameter_ko_012 | ko | — | run_station_task | json_content | 작업 좀 돌려. |
| invalid_parameter_ko_008 | ko | — | run_station_task | json_content | AGV '다섯'대로 시작해. |
| negative_control_en_001 | en | — | inspect_station | json_content | What is the current process status? |
| missing_parameter_en_004 | en | — | inspect_station | json_content | Inspect the station. |

---

Raw machine-readable results: `phase2_validation_ablation.json` / `phase2_validation_ablation.csv` in this directory.
