# Phase 2 — Validation-Layer Ablation (v2 benchmark)

Generated: 2026-06-11T02:03:23+00:00

Suite: **70 cases** across 12 categories · **R=3 repeats** · model `qwen3.5:2b`.

Cells: **A1/A2** = Ollama validation layer off/on · **B1/B2** = llama.cpp off/on. *off* = single LLM call, no repair retry, no rule-based fallback (intrinsic structured-output ability). *on* = full `propose_tool_call` path (repair retry + deterministic fallback). Rates carry Wilson 95% CIs.

## 1. Headline — Task Success Rate (tool + args correct)

| Provider | Layer OFF | Layer ON |
|---|---|---|
| Ollama | 62.9% [56–69] (n=210) | 64.3% [58–70] (n=210) |
| llama.cpp | 54.3% [48–61] (n=210) | 58.1% [51–65] (n=210) |

## 2. Validation-layer lift (ON − OFF)

| Provider | Task success Δ | Schema-valid Δ | Tool-correct Δ |
|---|---|---|---|
| Ollama | +1.4 pp | +36.7 pp | +1.0 pp |
| llama.cpp | +3.8 pp | +20.0 pp | +4.3 pp |

## 3. Per-cell diagnostic rates

| Metric | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| Task success | 62.9% | 64.3% | 54.3% | 58.1% |
| Tool correct | 71.0% | 71.9% | 60.0% | 64.3% |
| Args correct | 62.9% | 64.3% | 54.3% | 58.1% |
| JSON parse | 64.8% | 100.0% | 75.2% | 100.0% |
| Schema valid (1st-pass LLM) | 52.4% | 89.0% | 68.6% | 88.6% |
| Repair-retry rate | 0.0% | 16.7% | 0.0% | 12.9% |
| Rule-based fallback rate | 0.0% | 2.9% | 0.0% | 2.9% |
| Clarification appropriate | 67.4% | 69.6% | 45.7% | 51.4% |

Fallback correctness / repair success (of the cases that triggered them):

| Diagnostic | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| Fallback correctness | — | 0.0% | — | 0.0% |
| Repair success | — | 54.3% | — | 66.7% |

## 4. Per-category task success

| Category | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| positive_invocation | — | — | — | — |
| negative_control | 90.5% | 88.1% | 76.2% | 66.7% |
| ambiguous | 90.0% | 76.7% | 63.3% | 50.0% |
| parameter_extraction | — | — | — | — |
| multi_parameter | 100.0% | 100.0% | 100.0% | 100.0% |
| missing_parameter | 69.4% | 52.8% | 30.6% | 27.8% |
| long_request | — | — | — | — |
| kpi_acceptance | 0.0% | 0.0% | 50.0% | 45.8% |
| invalid_parameter | 10.0% | 56.7% | 3.3% | 60.0% |
| disambiguation | 62.5% | 62.5% | 62.5% | 66.7% |
| sequential | — | — | — | — |
| state_dependent | — | — | — | — |

## 5. Latency (ms)

| Cell | mean | p50 | p95 | p99 | mean w/ retry | mean w/o retry |
|---|---|---|---|---|---|---|
| A1 | 1543 | 1457 | 2152 | 2183 | — | 1543 |
| A2 | 1733 | 1619 | 2467 | 3634 | 2504 | 1579 |
| B1 | 3955 | 3788 | 6516 | 6715 | — | 3955 |
| B2 | 4307 | 4062 | 6545 | 9863 | 6074 | 4046 |

## 6. Per-language task success

| Lang | A1 | A2 | B1 | B2 |
|---|---|---|---|---|
| en | 61.0% | 64.2% | 54.5% | 58.5% |
| ko | 65.5% | 64.4% | 54.0% | 57.5% |

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
| disambiguation_en_004 | en | run_station_task | inspect_station | json_content | Work station 10. |

### A2

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| disambiguation_en_003 | en | run_station_task | inspect_station | json_content | Work station 3. |
| kpi_acceptance_en_004 | en | start_simulation | start_simulation | json_content | Run 5 AGVs and pass only if there are zero collisions. |
| kpi_acceptance_ko_008 | ko | start_simulation | start_simulation | json_content | 충돌 0건이면 통과로 AGV 6대 시뮬레이션 시작해. |
| invalid_parameter_ko_008 | ko | — | move_to_station | json_content | AGV '다섯'대로 시작해. |
| kpi_acceptance_ko_006 | ko | start_simulation | start_simulation | json_content | 처리량 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이면 통과로 AGV 8대 돌려줘. |
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| disambiguation_en_004 | en | run_station_task | inspect_station | json_content | Work station 10. |
| ambiguous_ko_007 | ko | — | run_station_task | json_content | 저거 처리해줘. |

### B1

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| invalid_parameter_ko_007 | ko | — | set_sim_speed | json_content | 속도를 0으로 설정해. |
| disambiguation_en_003 | en | run_station_task | inspect_station | json_content | Work station 3. |
| kpi_acceptance_en_004 | en | start_simulation | start_simulation | json_content | Run 5 AGVs and pass only if there are zero collisions. |
| kpi_acceptance_ko_008 | ko | start_simulation | start_simulation | json_content | 충돌 0건이면 통과로 AGV 6대 시뮬레이션 시작해. |
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| negative_control_en_008 | en | — | inspect_station | json_content | What actions are available for station 2? |
| negative_control_en_001 | en | — | inspect_station | json_content | What is the current process status? |
| disambiguation_en_004 | en | run_station_task | — | none | Work station 10. |

### B2

| Case | Lang | Expected | Actual | Path | Prompt |
|---|---|---|---|---|---|
| negative_control_en_004 | en | — | inspect_station | json_content | How does the AGV cell work? |
| disambiguation_en_003 | en | run_station_task | inspect_station | json_content | Work station 3. |
| kpi_acceptance_en_004 | en | start_simulation | start_simulation | json_content | Run 5 AGVs and pass only if there are zero collisions. |
| kpi_acceptance_ko_008 | ko | start_simulation | start_simulation | json_content | 충돌 0건이면 통과로 AGV 6대 시뮬레이션 시작해. |
| invalid_parameter_ko_008 | ko | — | run_station_task | json_content | AGV '다섯'대로 시작해. |
| ambiguous_en_004 | en | — | start_simulation | json_content | Start it. |
| negative_control_en_008 | en | — | inspect_station | json_content | What actions are available for station 2? |
| negative_control_en_001 | en | — | inspect_station | json_content | What is the current process status? |

---

Raw machine-readable results: `phase2_validation_ablation.json` / `phase2_validation_ablation.csv` in this directory.
