# LLM Provider Evaluation and Validation-Layer Optimization

## Problem

UE5 공정 제어용 Agent 시스템은 Tool Calling 기반으로 동작한다.

시스템은 사용자의 자연어 명령을 분석하여 시뮬레이션 제어, AGV 이동, 공정 작업 실행 등의 Tool을 호출한다.

초기 구현에서는 Ollama를 추론 백엔드로 사용하고 있었으나, 추론 최적화 및 향후 온프레미스 배포를 고려하여 llama.cpp 기반 추론 서버 도입 가능성을 검토하게 되었다.

하지만 단순히 추론 속도만 비교하는 것은 실제 Agent 품질을 설명하기 어렵다고 판단하였다.

따라서 다음 질문에 답하기 위한 벤치마크를 설계하였다.

* 어떤 Provider가 더 안정적으로 Tool Calling을 수행하는가?
* JSON 구조화 출력은 얼마나 안정적인가?
* Validation Layer는 실제로 도움이 되는가?
* Fine-tuning이 필요한 상황인가?

---

## Decision 1 — Provider Benchmark 먼저 수행

초기에는 llama.cpp를 도입하여 추론 최적화를 수행하는 것이 목표였다.

그러나 추론 엔진을 변경하기 전에 실제 품질 차이를 정량적으로 확인해야 한다고 판단하였다.

따라서 먼저 동일 모델(Qwen3.5:2B)을 기준으로 다음 비교 실험을 수행하였다.

* Ollama
* llama.cpp (CUDA Offload)

평가 항목:

* Tool Selection Accuracy
* JSON Parse Success
* Schema Validation Success
* Average Latency
* Retry Rate

### Result

실험 결과는 예상과 달랐다.

llama.cpp는 Tool Selection Accuracy가 더 높았지만,

Ollama는 JSON 및 Schema 안정성이 훨씬 높았다.

즉,

"어떤 Provider가 더 우수한가"

라는 질문에 단순한 답은 존재하지 않았다.

Provider마다 서로 다른 강점과 약점을 가진다는 사실을 확인하였다.

---

## Decision 2 — Validation Layer 효과 검증

초기 가설은 다음과 같았다.

"JSON Repair, Retry, Fallback을 추가하면 모든 Provider의 품질이 향상될 것이다."

이를 검증하기 위해 Validation Layer를 추가한 뒤 대규모 Ablation Benchmark를 수행하였다.

실험 규모:

* 133 Cases
* 4 Experimental Cells
* Repeat = 5
* Total Executions = 2,660

비교 대상:

* Ollama (Layer OFF)
* Ollama (Layer ON)
* llama.cpp (Layer OFF)
* llama.cpp (Layer ON)

---

## Unexpected Finding

실험 결과 Validation Layer는 Provider 중립적이지 않았다.

### Ollama

Validation Layer 적용 후

Task Success:

75.2%
→
54.3%

오히려 성능이 크게 감소하였다.

원인을 분석한 결과,

Repair Retry Prompt가 "반드시 Tool을 출력하라"는 형태로 작성되어 있었다.

따라서 원래 Tool을 호출하지 말아야 하는 상황에서도 강제로 Tool을 생성하게 되었다.

즉,

Schema Validity는 증가했지만 실제 Task Success는 감소하였다.

---

### llama.cpp

반대로 llama.cpp는 Validation Layer 적용 시 성능이 향상되었다.

원인은 llama.cpp의 JSON 출력 안정성이 낮기 때문이었다.

Rule-Based Fallback이 JSON 실패를 보완하면서 Task Success를 크게 끌어올렸다.

---

## Insight

이 실험을 통해 다음 사실을 확인하였다.

Validation Layer는 항상 성능을 향상시키지 않는다.

모델의 특성에 따라 동일한 후처리 로직이 전혀 다른 결과를 만들 수 있다.

즉,

"모델 성능"

과

"시스템 성능"

은 분리하여 평가해야 한다.

---

## Decision 3 — Fine-Tuning 보류

초기에는 JSON 출력 문제를 해결하기 위해 Fine-Tuning을 고려하였다.

그러나 Ablation 결과를 분석한 후 방향을 변경하였다.

발견된 주요 문제:

* Retry Prompt 설계 결함
* Validator Range Check 부재

이는 모델 문제가 아니라 시스템 문제였다.

따라서 즉시 Fine-Tuning을 진행하지 않고,

1. Retry Prompt 수정
2. Validation Logic 개선
3. Re-Benchmark

를 먼저 수행하기로 결정하였다.

---

## Engineering Takeaway

이 프로젝트를 통해 얻은 가장 중요한 교훈은 다음과 같다.

문제를 발견했을 때 즉시 모델을 교체하거나 Fine-Tuning을 수행하는 것이 아니라,

정량적 벤치마크와 Ablation Study를 통해

* 문제의 위치가 모델인지
* 문제의 위치가 시스템인지
* 실제 개선 비용 대비 효과가 무엇인지

를 먼저 검증해야 한다.

이를 통해 불필요한 Fine-Tuning 비용을 줄이고, 더 높은 ROI를 가지는 개선 방향을 식별할 수 있었다.
