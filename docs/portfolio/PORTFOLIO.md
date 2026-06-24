* * *

### 개요 (Overview)

**V-CORE**는 산업 현장의 운영 전략을 Unreal Engine 5 기반 디지털 트윈에서 검증하기 위한 **AI Agent 기반 시뮬레이션 제어 플랫폼**입니다. 사용자는 "AGV를 몇 대 투입할 것인가", "병목률 5% 이하의 최적 AGV 대수를 찾아줘"와 같은 자연어 요청을 입력하고, 시스템은 LangGraph 기반 에이전트 라우팅, 로컬 LLM Tool Calling, Validation Layer, UE5 Command Proxy를 거쳐 실제 시뮬레이션 실행과 KPI 리포트까지 자동화합니다. 여기에 다국어 Vector RAG와 typed graph를 결합해 운영 절차, 실시간 설비 상태, 과거 run KPI를 출처가 추적 가능한 답변으로 연결했습니다.

핵심 목표는 무거운 UE5 실행 환경을 사용자 PC에 직접 요구하지 않고, **Pixel Streaming 2와 웹 대시보드**를 통해 공정 상태를 제어·관찰하는 것입니다. 동시에 온프레미스 LLM을 운영 환경에 맞게 최적화하고, 프롬프트 증류 SFT를 통해 Tool-routing 안정성을 개선했습니다.

* * *

## 기술 스택 (Tech Stack)

| Category | Technologies |
| --- | --- |
| **Simulation Engine** | Unreal Engine 5.7, C++, UE5 StateTree, Pixel Streaming 2 |
| **Agent Orchestration** | LangGraph, Tool Calling, Tool Routing, State Management |
| **Backend** | FastAPI, SSE, WebSocket, UE5 Command Proxy |
| **Frontend** | React, Web Dashboard, Simulation Studio |
| **Knowledge / RAG** | Qdrant, bge-m3 (1024-dim), Multilingual Vector RAG, Hybrid GraphRAG, Vector/Lexical Reranking |
| **Data / Infra** | Firebase RTDB, PostgreSQL, Qdrant Managed Cloud (GCP), Docker, Perforce |
| **Local AI** | Qwen3.5-2B, llama.cpp, Ollama, QLoRA, GGUF(q4\_k\_m), OpenAI-compatible Embeddings API |

* * *

## 주요 기능 (Key Features)

### 1\. LangGraph 기반 시뮬레이션 제어 에이전트

**“채팅 입력에서 UE5 공정 제어까지 이어지는 2단계 Agent Pipeline”**

-   **1단계 Route Classification**: 사용자의 요청을 `robot_command`, `process_status`, `station_action_query`, `compare_runs`, `optimize_agv_count`, `general_chat / retrieve` 등 6개 라우트로 분류합니다. LLM 분류기에 keyword fallback을 결합해 정형 요청은 더 안정적으로 처리했습니다.
-   **2단계 Tool Planning**: `robot_command` 라우트에서는 9개 typed tool 중 하나를 선택합니다. 시뮬레이션 시작, 정지, 일시정지, 배속 변경, 특정 스테이션 작업 실행, 명령 취소 등을 UE5 Command Client로 전달합니다.
-   **진행 상태 스트리밍**: "분석 - 설정 확정 - AGV 투입"과 같은 중간 계획을 사용자에게 노출하고, UE5 텔레메트리와 완료 이벤트를 ReportAgent가 KPI 요약으로 변환합니다.

<div class="grid grid-cols-1 md:grid-cols-2 gap-6 my-8 items-start"><figure class="flex flex-col items-center"><img src="/images/project5/agent_layer1.png" alt="에이전트 라우팅 그래프" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 1. LangGraph 기반 라우트 분류 및 제어 흐름</figcaption></figure><figure class="flex flex-col items-center"><img src="/images/project5/agent_layer2.png" alt="툴 플래닝 그래프" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 2. robot_command 라우트의 2단계 Tool Planning</figcaption></figure></div>

* * *

### 2\. KPI 기반 공정 판정과 Simulation Studio

시뮬레이션 결과는 단순 로그가 아니라 공정 판단을 위한 지표로 구조화됩니다. 처리량, 평균 대기 시간, 충돌 횟수, 가동률, 병목률, 가동 AGV 수를 계산하고, 사용자가 acceptance 기준을 제시하면 PASS/FAIL 및 전체 verdict를 산출합니다.

| KPI | 정의 |
| --- | --- |
| **throughput** | 시간당 완료된 Load-to-Unload 운반 사이클 수 |
| **avg\_wait\_time** | AGV가 교차로 또는 스테이션에서 대기한 평균 시간 |
| **collision\_risk / count** | 런 동안 누적된 AGV 간 근접·충돌 횟수 |
| **uptime** | 전체 시간 중 AGV가 실제 작업한 비율 |
| **bottleneck\_rate** | 혼잡 히트맵에서 피크 밀도 60% 이상인 hot cell의 비율 |
| **active\_agvs** | 현재 실제 운행 중인 AGV 대수 |

<div class="grid grid-cols-1 md:grid-cols-2 gap-6 my-8 items-start"><figure class="flex flex-col items-center"><img src="/images/project5/simulation_studio.png" alt="시뮬레이션 스튜디오" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 3. 시나리오 목록, 실행 기록, 결과 KPI를 확인하는 Simulation Studio</figcaption></figure><figure class="flex flex-col items-center"><img src="/images/project5/congestion_heatmap.png" alt="혼잡 히트맵" class="max-w-md rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 4. AGV 위치 샘플링 기반 혼잡 히트맵</figcaption></figure></div>

* * *

### 3\. 기본 시뮬레이션 실행

"AGV 3대로 2배속 시뮬레이션해줘"와 같은 단일 명령형 요청은 `robot_command` 라우트에서 즉시 실행 가능한 Tool Call로 변환됩니다. 에이전트는 AGV 대수와 배속을 구조화하고, Validation Layer가 허용 범위를 검증한 뒤 UE5 Command Proxy에 시뮬레이션 시작 명령을 전달합니다.

-   **명령 파싱**: 자연어에서 `agv_count=3`, `speed_multiplier=2`를 추출합니다.
-   **실행 검증**: 현재 공정 상태와 AGV 투입 가능 범위를 확인한 뒤 안전한 명령만 전달합니다.
-   **실행 피드백**: 시작 결과와 초기 텔레메트리를 웹 대시보드에 표시해 사용자가 즉시 시뮬레이션 진행을 확인할 수 있게 했습니다.

<figure class="flex flex-col items-center my-8"><img src="/images/project5/simulation_optionA.png" alt="AGV 3대 2배속 시뮬레이션 실행" class="max-w-3xl rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 5. 사용 예시 A: AGV 3대, 2배속 시뮬레이션 실행</figcaption></figure>

<div class="gif-grid-container" style="grid-template-columns:50% 50%;margin-top:0;padding-top:0"><figure class="gif-item"><img src="/gifs/project5/simulation-optionA-start-ezgif.com-video-to-gif-converter.gif" alt="AGV 3대 2배속 시뮬레이션 시작" loading="lazy" style="display:block;margin:0 auto" class="modal-trigger cursor-pointer"><figcaption class="gif-caption">AGV 대수 및 실행 배속 설정 후 기본 시뮬레이션 시작</figcaption></figure><figure class="gif-item"><img src="/gifs/project5/simulation-optionA-agv-ezgif.com-video-to-gif-converter.gif" alt="AGV 3대 시뮬레이션 주행 화면" loading="lazy" style="display:block;margin:0 auto" class="modal-trigger cursor-pointer"><figcaption class="gif-caption">설정된 공정 경로를 따라 이동하는 AGV 3대의 주행 화면</figcaption></figure></div>

* * *

### 4\. Agentic Loop 기반 AGV 최적 대수 탐색

"병목률 5% 이하의 최적 AGV 대수를 찾아줘"와 같은 목표 탐색형 요청은 단일 Tool Call로 끝나지 않습니다. V-CORE는 최적화 요청을 사전 판정한 뒤 목표 지표를 파싱하고, UE5 상태에서 탐색 가능한 AGV 상한을 조회한 뒤 **observe - judge - decide - re-run** 폐루프를 실행합니다.

-   **목표 파싱**: "병목률 ≤ 5%"를 metric, comparator, threshold로 구조화합니다.
-   **후보 실행**: 후보 AGV 대수마다 KPI와 병목률을 산출하고 실행 기록에 저장합니다.
-   **결과 선택**: 목표를 만족하는 후보 중 가장 높은 처리 여유를 가진 AGV 대수를 선택하고, 모든 시도 내역을 한국어 리포트로 반환합니다.

<figure class="flex flex-col items-center my-8"><img src="/images/project5/simulation_optionB.png" alt="목표 탐색형 시뮬레이션" class="max-w-3xl rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 6. 사용 예시 B: 병목률 기준 AGV 대수 탐색</figcaption></figure>

<div class="gif-grid-container" style="grid-template-columns:50% 50%;margin-top:0;padding-top:0"><figure class="gif-item"><img src="/gifs/project5/simulation-optionB-start-ezgif.com-video-to-gif-converter.gif" alt="목표 탐색 시뮬레이션 시작" loading="lazy" style="display:block;margin:0 auto" class="modal-trigger cursor-pointer"><figcaption class="gif-caption">목표 병목률에 도달하기 위한 최적 AGV 대수 탐색 시작</figcaption></figure><figure class="gif-item"><img src="/gifs/project5/simulation-optionB-loop-ezgif.com-video-to-gif-converter.gif" alt="목표 탐색 반복 실행" loading="lazy" style="display:block;margin:0 auto" class="modal-trigger cursor-pointer"><figcaption class="gif-caption">목표를 만족할 때까지 AGV 대수를 조정하며 시뮬레이션 반복 실행</figcaption></figure><figure class="gif-item"><img src="/gifs/project5/simulation-optionB-success-ezgif.com-video-to-gif-converter.gif" alt="목표 탐색 성공 결과" loading="lazy" style="display:block;margin:0 auto" class="modal-trigger cursor-pointer"><figcaption class="gif-caption">목표 병목률 기준을 충족하는 AGV 대수 탐색 성공 결과</figcaption></figure></div>

* * *

### 5\. 시뮬레이션 상태 보고, 종료, 결과 보고

V-CORE는 시뮬레이션 실행 후에도 사용자의 후속 요청을 같은 대화 흐름 안에서 처리합니다. "현재 상태 알려줘"는 실시간 텔레메트리 요약으로, "시뮬레이션 종료해줘"는 종료 명령과 상태 확인으로, "결과 보고해줘"는 KPI 기반 자연어 리포트로 연결됩니다.

-   **상태 보고**: Firebase RTDB와 SSE로 수집한 AGV 위치, 가동률, 처리량, 대기 상태를 요약합니다.
-   **시뮬레이션 종료**: 진행 중인 UE5 run을 안전하게 정지하고 종료 상태를 사용자에게 확인시킵니다.
-   **결과 보고**: 완료된 run의 KPI, acceptance 판정, 병목 구간, 개선 제안을 한국어 리포트로 생성합니다.

<figure class="flex flex-col items-center my-8"><img src="/images/project5/process_status_terminate.png" alt="시뮬레이션 상태 보고와 종료 화면" class="max-w-3xl rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 7. 시뮬레이션 상태 보고 및 종료 명령 처리</figcaption></figure>

<div class="gif-grid-container" style="grid-template-columns:50% 50%;margin-top:0;padding-top:0"><figure class="gif-item"><img src="/gifs/project5/simulation-status-ezgif.com-video-to-gif-converter.gif" alt="시뮬레이션 상태 보고" loading="lazy" style="display:block;margin:0 auto" class="modal-trigger cursor-pointer"><figcaption class="gif-caption">실행 중인 시뮬레이션의 실시간 진행 상태 및 주요 지표 확인</figcaption></figure><figure class="gif-item"><img src="/gifs/project5/simulation-termination-ezgif.com-video-to-gif-converter.gif" alt="시뮬레이션 종료 처리" loading="lazy" style="display:block;margin:0 auto" class="modal-trigger cursor-pointer"><figcaption class="gif-caption">자연어 종료 명령을 검증하고 실행 중인 시뮬레이션 안전하게 종료</figcaption></figure><figure class="gif-item"><img src="/gifs/project5/simulation-optionA-result-ezgif.com-video-to-gif-converter.gif" alt="시뮬레이션 결과 보고" loading="lazy" style="display:block;margin:0 auto" class="modal-trigger cursor-pointer"><figcaption class="gif-caption">완료된 시뮬레이션의 KPI 및 개선점이 요약된 결과 리포트 확인</figcaption></figure></div>

<div class="grid grid-cols-1 md:grid-cols-2 gap-6 my-8 items-start"><figure class="flex flex-col items-center"><img src="/images/project5/simulation_optionA_result-1.png" alt="시뮬레이션 결과 보고 요약" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 8. 기본 시뮬레이션 결과 보고 요약</figcaption></figure><figure class="flex flex-col items-center"><img src="/images/project5/simulation_optionA_result-2.png" alt="시뮬레이션 결과 상세 KPI" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 9. KPI와 개선 포인트를 포함한 결과 상세</figcaption></figure></div>

* * *

### 6\. UE5 StateTree 기반 AGV 행동 설계

AGV 행동은 Behavior Tree보다 StateTree가 적합하다고 판단했습니다. AGV는 정해진 스플라인을 따라 이동하고, `pick_up`, `drop_off`처럼 상태와 전환 조건이 명확합니다. 복잡한 네비게이션 연산 대신 Pawn 기반 Transition Update를 StateTree Task로 정의하여 시뮬레이션 요구사항을 직관적으로 표현했습니다.

<div class="grid grid-cols-1 md:grid-cols-2 gap-6 my-8 items-start"><figure class="flex flex-col items-center"><img src="/images/project5/statetree1.png" alt="AGV StateTree 전체 구조" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 10. AGV 행동을 표현한 UE5 StateTree 구조</figcaption></figure><figure class="flex flex-col items-center"><img src="/images/project5/statetree2.png" alt="AGV StateTree 상세" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 11. 스테이션 도달 및 작업 상태 전환 로직</figcaption></figure></div>

* * *

### 7\. Graph RAG 기반 복합 운영 질의 응답

“현재 처리 가능한 스테이션과 각각의 마지막 병목률은?”과 같이 각 엔티티의 관계와 최신 KPI를 조인해야 하는 복합 질의는 일반 vector RAG의 평면 유사도로는 검색 품질이 떨어졌습니다. 그렇다고 모든 질의를 Graph RAG로 강제하면 속도 및 SOP 검색 품질이 떨어집니다.
따라서 질의 성격으로 검색 경로를 나누는 Hybrid Graph RAG를 채택했습니다. LangGraph의 classify 노드에서 관계형 질의로 판단되면 Graph로, 그 외 자유 텍스트는 기존 vector path로 라우팅하고 결과를 retrieve 노드로 전달합니다.

-   **Typed multi-hop 투영**: `Cell -> Zone -> Station -> Capability`(작업 가능 역량)와 `Cell -> Run -> Kpi`(최신 run 지표)를 하나의 ontology graph로 연결해, Zone별 작업 가능 스테이션·readiness/accessibility와 최신 저장 run의 `bottleneck_rate`를 한 번의 traversal로 추출합니다.
-   **Station별 per-zone KPI 귀속**: 근거를 cell-global 병목률 한 줄로 보고하던 것을, run의 `zone_heatmap`에서 산출한 per-zone 병목률(`latest_zone_metric`)로 각 스테이션 라인에 부착했습니다. 서로 다른 존의 스테이션이 자신의 병목률을 받고, cell-global 값은 fallback으로 라벨링해 유지합니다.
-   **Hybrid 분기와 Knowledge 경계**: 질의 성격을 `is_relational_query`로 판별해 관계형 질의는 graph path로, 자유 텍스트 SOP·사양 질의는 vector path(`bge-m3` 1024차원 + Qdrant cosine)로 분기합니다. 분기는 도메인이 의존하는 `KnowledgeGateway` 포트 뒤 `HybridGraphKnowledgeGateway` 어댑터 안에서 처리되어, LangGraph에는 단일 `retrieve` 노드만 노출됩니다.
-   **Memoized graph projection**: typed graph를 관계형 질의마다 재구축하지 않고 `(stations, runs)` 콘텐츠 fingerprint 기반으로 memoize해, 상태가 바뀔 때만 재구축하고 동일 상태의 다중 질의는 캐시된 graph를 공유합니다.


<figure class="flex flex-col items-center my-8"><img src="/images/project5/graphrag-sequence.png" alt="GraphRAG의 Hybrid 조건 분기" class="max-w-xl rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 12. GraphRAG의 Hybrid 조건 분기</figcaption></figure>

<div class="grid grid-cols-1 md:grid-cols-2 gap-6 my-8 items-start"><figure class="flex flex-col items-center"><img src="/images/project5/graphrag-chat1.png" alt="AGV StateTree 전체 구조" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 13. 복합 질의 채팅 입력</figcaption></figure><figure class="flex flex-col items-center"><img src="/images/project5/graphrag-chat2.png" alt="AGV StateTree 상세" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 14. GraphRAG 기반 결과 반환</figcaption></figure></div>

### 8\. Google Cloud VM 기반 원격 서비스 배포


Google Cloud VM에는 Pixel Streaming의 Signalling/Player 및 TURN 중계 계층만 배포하고, GPU 렌더링을 수행하는 UE5와 웹·LLM 백엔드는 로컬 워크스테이션에서 실행하였습니다. 운영 웹은 Cloudflare Tunnel을 통해 도메인으로 공개했으며, UE5는 outbound WebSocket으로 클라우드 Signalling Server에 영상을 송출하도록 구성하였습니다.




* * *

## 주요 문제 해결 과정 (Problem Solving)

### 1\. LLM 출력 불안정성과 Validation Layer

#### Problem

소규모 로컬 LLM은 tool 이름, JSON 구조, 필수 인자, 범위 값을 잘못 생성할 수 있습니다. LLM 응답을 곧바로 UE5에 전달하면 잘못된 공정 명령이 실행될 위험이 있습니다.

#### Solution

JSON 추출, schema 검증, range 검증, 제한적 repair retry, safe decline, rule-based fallback을 포함한 Validation Layer를 구축했습니다. 실행 가능한 명령만 UE5 Command Client로 전달하고, 모호하거나 위험한 요청은 되묻거나 거부합니다.

#### Result

LLM 출력 실패와 시스템 실행 실패를 분리했고, benchmark에서 validation layer의 실제 기여와 부작용을 ablation으로 측정할 수 있는 구조를 확보했습니다.

<div class="grid grid-cols-1 md:grid-cols-2 gap-6 my-8 items-start"><figure class="flex flex-col items-center"><img src="/images/project5/tool_success.png" alt="Tool routing 성공률" class="max-w-md rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 15. Tool selection schema와 종단 상태 검증</figcaption></figure><figure class="flex flex-col items-center"><img src="/images/project5/ablation_matrix.png" alt="Validation ablation matrix" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 16. Provider 및 Validation Layer 조합별 ablation 결과</figcaption></figure></div>

### 2\. 온프레미스 LLM 서빙 엔진 선택

#### Problem

외부 API를 쓰지 않는 환경에서 자연어 명령을 9개 실제 tool contract에 맞는 구조화 출력으로 변환해야 했습니다. 단순 latency뿐 아니라 JSON 안정성, 인자 정확성, 한국어·영어 요청 대응, validation layer와의 상호작용까지 평가해야 했습니다.

#### Solution

Ollama와 llama.cpp CUDA build를 동일 benchmark로 비교했습니다. 133개 라벨 케이스, 12개 카테고리, 4개 실험군, 각 케이스 5회 반복으로 총 2,660회 채점하고 Wilson 95% 신뢰구간을 부착했습니다.

#### Result

reasoning-off 및 CUDA 기반 llama.cpp 경로에서 추론 지연을 약 11.7초에서 약 2.4초로 줄였고, 운영 도메인에 더 적합한 서빙 경로를 판단할 수 있었습니다.

### 3\. Prompt-Distilled SFT Router

#### Problem

초기 프로덕션은 낮은 disambiguation 성능을 보완하기 위해 길고 정교한 시스템 프롬프트에 의존했습니다. tool이 추가될 때마다 프롬프트를 수정해야 했고, 컨텍스트 증가로 추론 비용이 커졌습니다.

#### Solution

Qwen3.5-2B 기반 QLoRA SFT를 수행하여 프롬프트 기반 tool-routing 규칙을 모델 가중치에 증류했습니다. Train 300 / Val 50 / Test 100 split으로 학습하고, 모든 라벨을 live ToolRouter.validate로 검증했습니다.

#### Result

Base 모델은 긴 운영 프롬프트가 제거되면 tool-routing 성공률이 49%에서 12%로 하락했지만, SFT 모델은 4줄 최소 프롬프트만으로 96%를 달성했습니다. 세부 지표도 disambiguation 30% -> 95%, KPI acceptance 50% -> 100%, invalid/missing parameter decline 0% -> 100%로 개선했습니다.

<figure class="flex flex-col items-center my-8"><img src="/images/project5/sft_heldout.png" alt="Prompt-distilled SFT held-out 평가" class="max-w-3xl rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans">Fig 17. Base + Minimal, Base + Full, SFT + Minimal 조건별 held-out 평가 결과</figcaption></figure>

### 4\. Adapter Toggle 기반 단일 엔드포인트 배포

#### Problem

라우팅 전용 SFT 모델과 일반 chat/report용 base 모델을 분리해 운영하려 했지만 8GB VRAM 예산을 초과했습니다. 또한 SFT 모델 하나로 일반 보고·대화까지 처리하면 반복 출력과 언어 누출 문제가 발생했습니다.

#### Solution

llama.cpp의 LoRA adapter on/off 기능을 활용해 base 모델 하나를 상주시켰습니다. routing 요청에서만 adapter scale을 1.0으로 켜고, chat/report/plan 요청에서는 0.0으로 꺼서 역할 분리를 유지했습니다.

#### Result

상주 모델 구조를 `Base 1개 + 소형 LoRA adapter`로 줄였고, routing 경로는 99.4%, chat/report 경로는 결함 0건, backend unit test 32건 통과를 확인했습니다.

### 5\. 검색 근거 없는 환각과 RAG 품질 회귀 방지

#### Problem

초기 Qdrant는 placeholder hash vector를 생성하는 seed scaffold에 머물렀고 application retrieval path가 연결되지 않았습니다. 모델이 절차를 내부 기억만으로 생성하면 근거 없는 운영 지침을 답할 수 있고, 검색이 한 번 성공하더라도 corpus·reranker·routing 변경 후 ranking과 citation 품질이 조용히 회귀할 위험이 있었습니다.

#### Solution

`classify -> retrieve -> rerank -> score filter -> sanitize -> cite/abstain` 경로를 LangGraph에 연결했습니다. 검색 문서는 untrusted input으로 취급해 instruction-like phrase를 neutralize하고 email·전화번호·주민등록번호·secret pattern을 redact했습니다. 또한 vector 6건, graph 2건, answer 3건의 소규모 deterministic regression set으로 retrieval, citation, faithfulness, grounding, abstention contract를 gate했습니다.

#### Result

checked-in baseline에서 vector retrieval recall@5 1.00 / nDCG@5 0.88, graph retrieval recall@3 1.00 / nDCG@3 1.00을 기록했고, 3개 answer case의 citation·faithfulness·grounding·abstention을 각각 1.00으로 고정했습니다. 각 turn에는 route, node path, retrieval hit, latency, estimated token, `low_grounding` / `possible_misroute`를 포함한 redacted trace를 남겨 실패 원인을 재현할 수 있게 했습니다.


### 6\. GraphRAG in-process 재구축 비용 제거 (memoized graph)

#### Problem

typed graph가 관계형 질의마다 **매번 처음부터 재구축**됐습니다. 모든 `OntologyNode`/`OntologyEdge`와 인접 맵이 바뀌지 않았어도 질의마다 다시 할당했고, graph는 어디에도 사용되지 않았습니다.

#### Solution

`build`를 fingerprint(`hashlib.sha1` over station `model_dump` + run id/status/timestamp/`kpis_json`) 기반 memoization 진입점으로 분리하고, 실제 구축은 `_build`로 옮겼습니다. 동일 fingerprint면 작은 LRU(`cache_size=8`, `OrderedDict`)에서 캐시된 graph를 그대로 반환하고, 상태가 실제로 바뀔 때만 재구축합니다. 캐시 graph는 retriever가 read-only로 공유합니다.

#### Result

per-query 재구축이 per-state-change 재구축으로 바뀌어, 상태가 같은 N개 질의가 graph를 1회만 구축합니다(`builds==1`). 캐시 재사용·fingerprint 무효화·다중 질의 1회 구축 회귀 테스트를 추가했고 백엔드 스위트 127건이 통과했습니다. 별도 graph 서비스 없이 in-process 영속(상태 변경 시까지 유지) store를 달성했으며, 프로세스 경계를 넘는 외부 graph store(Neo4j/RDF)는 CSP 향후 과제로 남았습니다.

<div class="grid grid-cols-1 md:grid-cols-2 gap-6 my-8 items-start"><figure class="flex flex-col items-center"><img src="/images/project5/graphrag-before.png" alt="AGV StateTree 전체 구조" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 18. 캐싱 적용 전</figcaption></figure><figure class="flex flex-col items-center"><img src="/images/project5/graphrag-after.png" alt="AGV StateTree 상세" class="w-full rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 19. 캐싱 적용 후</figcaption></figure></div>

* * *

## 결과 (Results)

-   **UE5 디지털 트윈 제어 자동화**: 채팅 입력부터 명령 라우팅, UE5 시뮬레이션 구동, 실시간 텔레메트리, 웹 대시보드, 합격/불합격 보고까지 연결했습니다.
-   **로컬 LLM 운영 최적화**: 외부 호스팅 LLM API 없이 온프레미스 tool planning을 수행하고, llama.cpp CUDA build와 reasoning-off 설정으로 latency를 줄였습니다.
-   **Tool-routing 성능 개선**: 프롬프트 증류 QLoRA SFT를 통해 4줄 최소 프롬프트 조건에서 tool-routing 성공률 96%를 달성했습니다.
-   **실시간 공정 관찰**: Firebase RTDB와 SSE를 통해 AGV 가동률, 처리율, 충돌 위험, 혼잡 히트맵을 웹 UI에 시각화했습니다.
-   **근거 기반 운영 지식 확장**: 16개 Qdrant point와 typed graph를 LangGraph에 연결해 다국어 SOP 검색, 출처 인용, 명시적 abstention, 최신 run KPI 결합 질의를 하나의 운영 대화 흐름으로 통합했습니다.
-   **RAG 회귀 품질 정량화**: 소규모 regression set에서 vector recall@5 1.00, graph recall@3 1.00, citation·faithfulness·grounding·abstention 1.00을 기준선으로 고정했습니다.

<div class="grid grid-cols-1 md:grid-cols-2 gap-6 my-8 items-start"><figure class="flex flex-col items-center"><img src="/images/project5/simulationresult_success.png" alt="시뮬레이션 성공 결과" class="max-w-sm rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 19. Acceptance 기준을 만족한 성공 결과</figcaption></figure><figure class="flex flex-col items-center"><img src="/images/project5/simulationresult_fail.png" alt="시뮬레이션 실패 결과" class="max-w-sm rounded-lg shadow-md mb-2 modal-trigger cursor-pointer"><figcaption class="text-sm text-gray-500 italic font-sans text-center">Fig 20. 기준 미달 또는 충돌 위험에 따른 실패 판정</figcaption></figure></div>

* * *

## 한계 및 개선점 (Limitations)

-   **라우팅 전용 SFT의 범위 제한**: SFT 모델은 tool-routing에는 강하지만 일반 대화·보고 생성에는 적합하지 않아 adapter toggle 방식으로 역할을 분리했습니다.
-   **다중 사용자 검증 필요**: adapter toggle은 단일 사용자 환경에서는 효과적이었지만, 다중 사용자 요청이 동시에 들어오는 환경의 동시성 검증이 추가로 필요합니다.
-   **고정 Tool Set 의존성**: 현재 SFT는 학습 당시의 tool schema에 최적화되어 있어 tool 추가 또는 schema 변경 시 재학습 또는 범용 라우팅 규칙 학습 전략이 필요합니다.
-   **MLOps 자동화 부족**: 모델 버전 관리, 평가 자동화, 배포 추적을 더 체계화할 필요가 있습니다.
