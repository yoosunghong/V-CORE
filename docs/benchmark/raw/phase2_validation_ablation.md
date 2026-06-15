# Phase 2 — Validation-Layer Ablation (v2 benchmark)

Generated: 2026-06-10T15:01:09+00:00

Suite: **133 cases** across 12 categories · **R=5 repeats** · model `qwen3.5:2b`.

Cells: **A1/A2** = Ollama validation layer off/on · **B1/B2** = llama.cpp off/on. *off* = single LLM call, no repair retry, no rule-based fallback (intrinsic structured-output ability). *on* = full `propose_tool_call` path (repair retry + deterministic fallback). Rates carry Wilson 95% CIs.

## 1. Headline — Task Success Rate (tool + args correct)

| Provider | Layer OFF | Layer ON |
|---|---|---|
| Ollama | 75.2% [72–78] (n=665) | 54.3% [50–58] (n=665) |
| llama.cpp | 53.5% [50–57] (n=665) | 66.2% [62–70] (n=665) |

## 2. Validation-layer lift (ON − OFF)

| Provider | Task success Δ | Schema-valid Δ | Tool-correct Δ |
|---|---|---|---|
| Ollama | -20.9 pp | +24.1 pp | -20.9 pp |
| llama.cpp | +12.6 pp | +0.2 pp | +13.4 pp |

## 3. Per-cell diagnostic rates

| Metric | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| Task success | 75.2% | 54.3% | 53.5% | 66.2% |
| Tool correct | 79.7% | 58.8% | 53.5% | 66.9% |
| Args correct | 75.2% | 54.3% | 53.5% | 66.2% |
| JSON parse | 83.3% | 98.5% | 24.4% | 24.5% |
| Schema valid (1st-pass LLM) | 74.1% | 98.2% | 24.4% | 24.5% |
| Repair-retry rate | 0.0% | 26.2% | 0.0% | 76.4% |
| Rule-based fallback rate | 0.0% | 0.0% | 0.0% | 38.6% |
| Clarification appropriate | 64.3% | 0.9% | 93.9% | 78.3% |

Fallback correctness / repair success (of the cases that triggered them):

| Diagnostic | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| Fallback correctness | — | — | — | 46.3% |
| Repair success | — | 5.7% | — | 60.0% |

## 4. Per-category task success

| Category | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| positive_invocation | 98.6% | 98.6% | 65.7% | 85.7% |
| negative_control | 94.3% | 2.9% | 100.0% | 100.0% |
| ambiguous | 86.0% | 0.0% | 100.0% | 100.0% |
| parameter_extraction | 100.0% | 100.0% | 45.5% | 100.0% |
| multi_parameter | 100.0% | 100.0% | 4.0% | 10.0% |
| missing_parameter | 61.7% | 0.0% | 96.7% | 81.7% |
| long_request | 100.0% | 100.0% | 12.0% | 26.0% |
| kpi_acceptance | 20.0% | 22.0% | 0.0% | 60.0% |
| invalid_parameter | 4.0% | 0.0% | 76.0% | 22.0% |
| disambiguation | 61.7% | 60.0% | 48.3% | 83.3% |
| sequential | 90.0% | 90.0% | 8.0% | 24.0% |
| state_dependent | 72.0% | 86.0% | 56.0% | 70.0% |

## 5. Latency (ms)

| Cell | mean | p50 | p95 | p99 | mean w/ retry | mean w/o retry |
|---|---|---|---|---|---|---|
| A1 | 1360 | 1176 | 2106 | 2153 | — | 1360 |
| A2 | 1663 | 1168 | 3281 | 4213 | 2978 | 1197 |
| B1 | 1499 | 1538 | 1559 | 1582 | — | 1499 |
| B2 | 2893 | 3091 | 3911 | 3949 | 3335 | 1461 |

## 6. Per-language task success

| Lang | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| en | 77.8% | 57.0% | 56.7% | 63.8% |
| ko | 72.0% | 51.0% | 49.7% | 69.0% |

## 7. Failure gallery

### A1

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| missing_parameter_en_002 | en | — | inspect_station | json_content | Run the task. |
| invalid_parameter_en_003 | en | — | set_sim_speed | json_content | Set the speed to -2x. |
| state_dependent_en_004 | en | resume_simulation | — | none | Pick it back up where we left off. |
| invalid_parameter_ko_009 | ko | — | inspect_station | json_content | 스테이션 999 검사해. |
| kpi_acceptance_ko_005 | ko | start_simulation | start_simulation | json_content | 처리량 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이면 통과로 AGV 4대 돌려줘. |
| invalid_parameter_ko_008 | ko | — | move_to_station | json_content | AGV '다섯'대로 시작해. |
| missing_parameter_en_004 | en | — | inspect_station | json_content | Inspect the station. |

### A2

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| ambiguous_ko_009 | ko | — | run_station_task | json_content | 알아서 해줘. |
| missing_parameter_en_002 | en | — | run_station_task | json_content | Run the task. |
| invalid_parameter_en_003 | en | — | set_sim_speed | json_content | Set the speed to -2x. |
| ambiguous_ko_007 | ko | — | run_station_task | json_content | 저거 처리해줘. |
| negative_control_ko_012 | ko | — | inspect_station | json_content | AGV 셀이 어떻게 동작하나요? |
| missing_parameter_ko_012 | ko | — | run_station_task | json_content | 작업 좀 돌려. |
| invalid_parameter_ko_009 | ko | — | inspect_station | json_content | 스테이션 999 검사해. |

### B1

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| long_request_en_002 | en | start_simulation | — | none | We had a rough morning shift, throughput dipped and the floor was a… |
| sequential_ko_006 | ko | move_to_station | — | none | 스테이션 7으로 이동한 다음 거기서 작업 실행해. |
| multi_parameter_ko_007 | ko | start_simulation | — | none | AGV 4대로 2.0배속 시뮬레이션 시작해. |
| state_dependent_en_004 | en | resume_simulation | — | none | Pick it back up where we left off. |
| positive_invocation_ko_009 | ko | pause_simulation | — | none | 시뮬레이션 일시정지. |
| long_request_ko_009 | ko | move_to_station | — | none | 지난 런에서 도크 근처에 AGV가 멈춰 있는 걸 봤는데, 자세히 보게 그냥 AGV를 스테이션 4으로 옮겨줘. |
| long_request_ko_010 | ko | move_to_station | — | none | 지난 런에서 도크 근처에 AGV가 멈춰 있는 걸 봤는데, 자세히 보게 그냥 AGV를 스테이션 8으로 옮겨줘. |
| multi_parameter_ko_009 | ko | run_station_task | — | none | 스테이션 3 작업을 높은 우선순위로 실행해. |

### B2

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| long_request_en_002 | en | start_simulation | — | none | We had a rough morning shift, throughput dipped and the floor was a… |
| sequential_ko_006 | ko | move_to_station | start_simulation | rule_based_fallback | 스테이션 7으로 이동한 다음 거기서 작업 실행해. |
| multi_parameter_ko_007 | ko | start_simulation | set_sim_speed | rule_based_fallback | AGV 4대로 2.0배속 시뮬레이션 시작해. |
| invalid_parameter_en_003 | en | — | set_sim_speed | rule_based_fallback | Set the speed to -2x. |
| state_dependent_en_004 | en | resume_simulation | — | none | Pick it back up where we left off. |
| long_request_ko_009 | ko | move_to_station | pause_simulation | rule_based_fallback | 지난 런에서 도크 근처에 AGV가 멈춰 있는 걸 봤는데, 자세히 보게 그냥 AGV를 스테이션 4으로 옮겨줘. |
| long_request_ko_010 | ko | move_to_station | pause_simulation | rule_based_fallback | 지난 런에서 도크 근처에 AGV가 멈춰 있는 걸 봤는데, 자세히 보게 그냥 AGV를 스테이션 8으로 옮겨줘. |
| multi_parameter_ko_009 | ko | run_station_task | start_simulation | rule_based_fallback | 스테이션 3 작업을 높은 우선순위로 실행해. |

---

Raw machine-readable results: `phase2_validation_ablation.json` / `phase2_validation_ablation.csv` in this directory.
