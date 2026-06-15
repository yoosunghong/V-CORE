# Phase 2 — Validation-Layer Ablation (v2 benchmark)

Generated: 2026-06-10T18:17:55+00:00

Suite: **70 cases** across 12 categories · **R=3 repeats** · model `qwen3.5:2b`.

Cells: **A1/A2** = Ollama validation layer off/on · **B1/B2** = llama.cpp off/on. *off* = single LLM call, no repair retry, no rule-based fallback (intrinsic structured-output ability). *on* = full `propose_tool_call` path (repair retry + deterministic fallback). Rates carry Wilson 95% CIs.

## 1. Headline — Task Success Rate (tool + args correct)

| Provider | Layer OFF | Layer ON |
|---|---|---|
| Ollama | 63.3% [57–70] (n=210) | 39.5% [33–46] (n=210) |
| llama.cpp | 51.4% [45–58] (n=210) | 34.3% [28–41] (n=210) |

## 2. Validation-layer lift (ON − OFF)

| Provider | Task success Δ | Schema-valid Δ | Tool-correct Δ |
|---|---|---|---|
| Ollama | -23.8 pp | +26.2 pp | -23.3 pp |
| llama.cpp | -17.1 pp | +17.1 pp | -17.1 pp |

## 3. Per-cell diagnostic rates

| Metric | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| Task success | 63.3% | 39.5% | 51.4% | 34.3% |
| Tool correct | 71.4% | 48.1% | 57.1% | 40.0% |
| Args correct | 63.3% | 39.5% | 51.4% | 34.3% |
| JSON parse | 68.1% | 100.0% | 75.2% | 100.0% |
| Schema valid (1st-pass LLM) | 52.4% | 78.6% | 71.4% | 88.6% |
| Repair-retry rate | 0.0% | 56.7% | 0.0% | 38.1% |
| Rule-based fallback rate | 0.0% | 2.9% | 0.0% | 2.9% |
| Clarification appropriate | 67.4% | 31.9% | 41.3% | 13.0% |

Fallback correctness / repair success (of the cases that triggered them):

| Diagnostic | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| Fallback correctness | — | 0.0% | — | 0.0% |
| Repair success | — | 37.0% | — | 22.5% |

## 4. Per-category task success

| Category | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| positive_invocation | — | — | — | — |
| negative_control | 97.6% | 35.7% | 69.0% | 0.0% |
| ambiguous | 90.0% | 10.0% | 66.7% | 0.0% |
| parameter_extraction | — | — | — | — |
| multi_parameter | 100.0% | 100.0% | 100.0% | 100.0% |
| missing_parameter | 63.9% | 22.2% | 22.2% | 0.0% |
| long_request | — | — | — | — |
| kpi_acceptance | 4.2% | 0.0% | 50.0% | 50.0% |
| invalid_parameter | 6.7% | 60.0% | 0.0% | 60.0% |
| disambiguation | 62.5% | 62.5% | 62.5% | 75.0% |
| sequential | — | — | — | — |
| state_dependent | — | — | — | — |

## 5. Latency (ms)

| Cell | mean | p50 | p95 | p99 | mean w/ retry | mean w/o retry |
|---|---|---|---|---|---|---|
| A1 | 1561 | 1456 | 2206 | 2270 | — | 1561 |
| A2 | 2373 | 2363 | 3980 | 4332 | 3127 | 1387 |
| B1 | 3736 | 3397 | 6367 | 6467 | — | 3736 |
| B2 | 4970 | 4732 | 9667 | 11609 | 7502 | 3412 |

## 6. Per-language task success

| Lang | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| en | 61.0% | 40.7% | 51.2% | 36.6% |
| ko | 66.7% | 37.9% | 51.7% | 31.0% |

## 7. Failure gallery

### A1

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| invalid_parameter_ko_007 | ko | — | set_sim_speed | json_content | 속도를 0으로 설정해. |
| disambiguation_en_003 | en | run_station_task | inspect_station | json_content | Work station 3. |
| missing_parameter_en_005 | en | — | run_station_task | json_content | Send the AGV over. |
| kpi_acceptance_en_004 | en | start_simulation | start_simulation | json_content | Run 5 AGVs and pass only if there are zero collisions. |
| kpi_acceptance_ko_008 | ko | start_simulation | start_simulation | json_content | 충돌 0건이면 통과로 AGV 6대 시뮬레이션 시작해. |
| invalid_parameter_ko_008 | ko | — | move_to_station | json_content | AGV '다섯'대로 시작해. |
| kpi_acceptance_ko_006 | ko | start_simulation | start_simulation | json_content | 처리량 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이면 통과로 AGV 8대 돌려줘. |
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |

### A2

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| disambiguation_en_003 | en | run_station_task | inspect_station | json_content | Work station 3. |
| missing_parameter_en_005 | en | — | run_station_task | json_content | Send the AGV over. |
| kpi_acceptance_en_004 | en | start_simulation | start_simulation | json_content | Run 5 AGVs and pass only if there are zero collisions. |
| kpi_acceptance_ko_008 | ko | start_simulation | start_simulation | json_content | 충돌 0건이면 통과로 AGV 6대 시뮬레이션 시작해. |
| negative_control_ko_011 | ko | — | run_station_task | json_content | 안녕하세요. |
| invalid_parameter_ko_008 | ko | — | move_to_station | json_content | AGV '다섯'대로 시작해. |
| kpi_acceptance_ko_006 | ko | start_simulation | start_simulation | json_content | 처리량 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이면 통과로 AGV 8대 돌려줘. |
| ambiguous_en_005 | en | — | run_station_task | json_content | Go ahead with that. |

### B1

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| invalid_parameter_ko_007 | ko | — | set_sim_speed | json_content | 속도를 0으로 설정해. |
| negative_control_en_004 | en | — | run_station_task | json_content | How does the AGV cell work? |
| disambiguation_en_003 | en | run_station_task | inspect_station | json_content | Work station 3. |
| missing_parameter_en_005 | en | — | run_station_task | json_content | Send the AGV over. |
| kpi_acceptance_en_004 | en | start_simulation | start_simulation | json_content | Run 5 AGVs and pass only if there are zero collisions. |
| kpi_acceptance_ko_008 | ko | start_simulation | start_simulation | json_content | 충돌 0건이면 통과로 AGV 6대 시뮬레이션 시작해. |
| invalid_parameter_ko_008 | ko | — | run_station_task | json_content | AGV '다섯'대로 시작해. |
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |

### B2

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| negative_control_en_004 | en | — | run_station_task | json_content | How does the AGV cell work? |
| disambiguation_en_003 | en | run_station_task | inspect_station | json_content | Work station 3. |
| missing_parameter_en_005 | en | — | move_to_station | json_content | Send the AGV over. |
| kpi_acceptance_en_004 | en | start_simulation | start_simulation | json_content | Run 5 AGVs and pass only if there are zero collisions. |
| kpi_acceptance_ko_008 | ko | start_simulation | start_simulation | json_content | 충돌 0건이면 통과로 AGV 6대 시뮬레이션 시작해. |
| negative_control_ko_011 | ko | — | run_station_task | json_content | 안녕하세요. |
| invalid_parameter_ko_008 | ko | — | run_station_task | json_content | AGV '다섯'대로 시작해. |
| ambiguous_en_005 | en | — | run_station_task | json_content | Go ahead with that. |

---

Raw machine-readable results: `phase2_validation_ablation.json` / `phase2_validation_ablation.csv` in this directory.
