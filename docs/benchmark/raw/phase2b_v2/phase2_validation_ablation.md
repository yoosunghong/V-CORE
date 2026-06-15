# Phase 2 — Validation-Layer Ablation (v2 benchmark)

Generated: 2026-06-11T01:18:06+00:00

Suite: **70 cases** across 12 categories · **R=3 repeats** · model `qwen3.5:2b`.

Cells: **A1/A2** = Ollama validation layer off/on · **B1/B2** = llama.cpp off/on. *off* = single LLM call, no repair retry, no rule-based fallback (intrinsic structured-output ability). *on* = full `propose_tool_call` path (repair retry + deterministic fallback). Rates carry Wilson 95% CIs.

## 1. Headline — Task Success Rate (tool + args correct)

| Provider | Layer OFF | Layer ON |
|---|---|---|
| Ollama | 61.0% [54–67] (n=210) | 50.5% [44–57] (n=210) |
| llama.cpp | 50.5% [44–57] (n=210) | 49.0% [42–56] (n=210) |

## 2. Validation-layer lift (ON − OFF)

| Provider | Task success Δ | Schema-valid Δ | Tool-correct Δ |
|---|---|---|---|
| Ollama | -10.5 pp | +31.9 pp | -10.5 pp |
| llama.cpp | -1.4 pp | +15.2 pp | -1.9 pp |

## 3. Per-cell diagnostic rates

| Metric | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| Task success | 61.0% | 50.5% | 50.5% | 49.0% |
| Tool correct | 69.5% | 59.0% | 56.7% | 54.8% |
| Args correct | 61.0% | 50.5% | 50.5% | 49.0% |
| JSON parse | 69.0% | 100.0% | 77.1% | 100.0% |
| Schema valid (1st-pass LLM) | 54.8% | 86.7% | 72.9% | 88.1% |
| Repair-retry rate | 0.0% | 28.6% | 0.0% | 21.4% |
| Rule-based fallback rate | 0.0% | 2.9% | 0.0% | 2.9% |
| Clarification appropriate | 64.5% | 47.8% | 39.9% | 35.5% |

Fallback correctness / repair success (of the cases that triggered them):

| Diagnostic | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| Fallback correctness | — | 0.0% | — | 0.0% |
| Repair success | — | 36.7% | — | 44.4% |

## 4. Per-category task success

| Category | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| positive_invocation | — | — | — | — |
| negative_control | 90.5% | 69.0% | 61.9% | 42.9% |
| ambiguous | 86.7% | 36.7% | 66.7% | 33.3% |
| parameter_extraction | — | — | — | — |
| multi_parameter | 100.0% | 100.0% | 100.0% | 100.0% |
| missing_parameter | 61.1% | 25.0% | 25.0% | 8.3% |
| long_request | — | — | — | — |
| kpi_acceptance | 0.0% | 0.0% | 45.8% | 50.0% |
| invalid_parameter | 10.0% | 56.7% | 0.0% | 60.0% |
| disambiguation | 62.5% | 66.7% | 66.7% | 75.0% |
| sequential | — | — | — | — |
| state_dependent | — | — | — | — |

## 5. Latency (ms)

| Cell | mean | p50 | p95 | p99 | mean w/ retry | mean w/o retry |
|---|---|---|---|---|---|---|
| A1 | 1523 | 1450 | 2111 | 2155 | — | 1523 |
| A2 | 2015 | 1881 | 3424 | 3787 | 2983 | 1627 |
| B1 | 4112 | 3767 | 6814 | 7213 | — | 4112 |
| B2 | 4745 | 4249 | 9992 | 12728 | 7834 | 3902 |

## 6. Per-language task success

| Lang | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| en | 61.0% | 51.2% | 52.0% | 52.8% |
| ko | 60.9% | 49.4% | 48.3% | 43.7% |

## 7. Failure gallery

### A1

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| invalid_parameter_ko_007 | ko | — | set_sim_speed | json_content | 속도를 0으로 설정해. |
| disambiguation_en_003 | en | run_station_task | inspect_station | json_content | Work station 3. |
| kpi_acceptance_en_004 | en | start_simulation | start_simulation | json_content | Run 5 AGVs and pass only if there are zero collisions. |
| kpi_acceptance_ko_008 | ko | start_simulation | start_simulation | json_content | 충돌 0건이면 통과로 AGV 6대 시뮬레이션 시작해. |
| invalid_parameter_ko_008 | ko | — | move_to_station | json_content | AGV '다섯'대로 시작해. |
| kpi_acceptance_ko_006 | ko | start_simulation | start_simulation | json_content | 처리량 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이면 통과로 AGV 8대 돌려줘. |
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| negative_control_en_008 | en | — | inspect_station | json_content | What actions are available for station 2? |

### A2

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| disambiguation_en_003 | en | run_station_task | inspect_station | json_content | Work station 3. |
| missing_parameter_en_005 | en | — | run_station_task | json_content | Send the AGV over. |
| kpi_acceptance_en_004 | en | start_simulation | start_simulation | json_content | Run 5 AGVs and pass only if there are zero collisions. |
| kpi_acceptance_ko_008 | ko | start_simulation | start_simulation | json_content | 충돌 0건이면 통과로 AGV 6대 시뮬레이션 시작해. |
| invalid_parameter_ko_008 | ko | — | move_to_station | json_content | AGV '다섯'대로 시작해. |
| kpi_acceptance_ko_006 | ko | start_simulation | start_simulation | json_content | 처리량 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이면 통과로 AGV 8대 돌려줘. |
| ambiguous_en_005 | en | — | run_station_task | json_content | Go ahead with that. |
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |

### B1

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| invalid_parameter_ko_007 | ko | — | set_sim_speed | json_content | 속도를 0으로 설정해. |
| disambiguation_en_003 | en | run_station_task | inspect_station | json_content | Work station 3. |
| missing_parameter_en_005 | en | — | run_station_task | json_content | Send the AGV over. |
| kpi_acceptance_en_004 | en | start_simulation | start_simulation | json_content | Run 5 AGVs and pass only if there are zero collisions. |
| kpi_acceptance_ko_008 | ko | start_simulation | start_simulation | json_content | 충돌 0건이면 통과로 AGV 6대 시뮬레이션 시작해. |
| invalid_parameter_ko_008 | ko | — | run_station_task | json_content | AGV '다섯'대로 시작해. |
| kpi_acceptance_ko_006 | ko | start_simulation | start_simulation | json_content | 처리량 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이면 통과로 AGV 8대 돌려줘. |
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |

### B2

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| disambiguation_en_003 | en | run_station_task | inspect_station | json_content | Work station 3. |
| missing_parameter_en_005 | en | — | run_station_task | json_content | Send the AGV over. |
| kpi_acceptance_en_004 | en | start_simulation | start_simulation | json_content | Run 5 AGVs and pass only if there are zero collisions. |
| kpi_acceptance_ko_008 | ko | start_simulation | start_simulation | json_content | 충돌 0건이면 통과로 AGV 6대 시뮬레이션 시작해. |
| negative_control_ko_011 | ko | — | run_station_task | json_content | 안녕하세요. |
| invalid_parameter_ko_008 | ko | — | run_station_task | json_content | AGV '다섯'대로 시작해. |
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| negative_control_en_008 | en | — | inspect_station | json_content | What actions are available for station 2? |

---

Raw machine-readable results: `phase2_validation_ablation.json` / `phase2_validation_ablation.csv` in this directory.
