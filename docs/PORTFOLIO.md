# VCORE — 산업 운영 전략 사전 검증을 위한 AI Twin 플랫폼

> 자연어 명령으로 UE5 AGV 공정 시뮬레이션을 구동·검증하는 온프레미스 AI Twin 플랫폼
> 포트폴리오 문서 · 2026-06

---

## 1. 개요

**VCORE**는 산업 현장의 운영 전략(예: "AGV를 몇 대 투입할 것인가", "물류 동선을 어떻게 바꿀 것인가")을
**실제 설비에 적용하기 전에 디지털 트윈 위에서 미리 검증**하는 플랫폼이다.

핵심 아이디어는 두 가지다.

1. **검증 가능한 트윈** — Unreal Engine 5로 구현한 AGV(무인 운반 차량) 셀이 실제 공정을 모사하고,
   처리량·평균 대기·충돌·가동률·병목률 등의 KPI를 실시간으로 산출한다.
2. **자연어로 실험을 설계하는 AI 에이전트** — 운영자는 SQL이나 시나리오 편집기 대신 채팅으로
   "AGV 3대로 2배속 돌려줘", "병목률 5% 이하를 만족하는 최소 AGV 대수를 찾아줘" 같은 명령을 내린다.
   에이전트는 이를 구조화된 제어 명령으로 변환해 트윈을 구동하고, **합격/불합격 판정(verdict)**까지 붙여
   결과를 보고한다.

시스템은 두 개의 서브시스템으로 구성된다.

- **UE5 시뮬레이션 엔진** — AGV 셀 3D 시뮬레이션, 실시간 이벤트/충돌 감지, KPI 로깅, 픽셀 스트리밍 송출.
- **웹 + LLM 스택** — LangGraph 멀티 에이전트 챗봇(FastAPI) + React 오버레이 + 온프레미스 LLM 추론 서버.

이 프로젝트의 차별점은 **"작동하는 데모"를 넘어, 각 기술 선택을 정량적 근거(2,660회 벤치마크,
Wilson 신뢰구간, A/B/C 평가)로 방어했다**는 점이다.

---

## 2. 주요 달성 (Key Performance)

| 항목 | 결과 |
|---|---|
| **엔드투엔드 데모** | 채팅 → 명령 라우팅 → UE5 시뮬레이션 구동 → 실시간 텔레메트리(SSE) → 웹 대시보드 → 합격/불합격 보고까지 완전 자동 |
| **LLM 벤치마크 규모** | 133 케이스 × 12 카테고리 × 4 실험군 × 반복 5회 = **2,660회** 채점, 전 항목 Wilson 95% 신뢰구간 부착 |
| **검증 레이어 결함 규명** | 운영 중이던 후처리 레이어가 최고 성능 모델을 **−21pp** 악화시키고 있음을 발견·수정 → A2 54.3% → **75.9%** (CI 비중첩) |
| **프롬프트만으로 KPI 추출** | `kpi_acceptance` 정확도 **22% → 94%** (3줄 프롬프트 변경, 학습 없음) |
| **서빙 플래그만으로 도구 변별** | `disambiguation` **63% → 91.7%** (동일 가중치, reasoning-off llama.cpp) |
| **추론 latency** | llama.cpp CUDA 빌드 + reasoning-off로 disambiguation 경로 **~11.7s → ~2.4s** |
| **프롬프트 증류(QLoRA SFT)** | 긴 운영 프롬프트 의존을 제거 — 4줄 최소 프롬프트로 tool-routing **49% → 96%** (held-out 100행) |
| **SFT 비용** | 0.58% / 43MB LoRA 어댑터, RTX 4060 Ti 8GB에서 **~7분** 학습, eval-loss 0.0315 → 0.0029 |
| **단일 모델 통합(8GB VRAM)** | 두 물리 모델(`routing_split`) → **베이스 1개 + 22MB LoRA를 per-request 토글**(adapter_toggle)로 접음 → 라우팅 **99.4%**(route+action) + **무결점** 대화/보고를 단일 llama.cpp 엔드포인트에서 |

---

## 3. 기술 스택

| 레이어 | 기술 |
|---|---|
| 시뮬레이션 | **Unreal Engine 5 (C++)** — `AAGVSimController` 가 AGV 셀과 제어 라우트(`:7777` HTTP 서버) 구동 |
| 영상 전송 | **Pixel Streaming 2** (UE5 → WebRTC → 브라우저 iframe) |
| 백엔드 | **Python / FastAPI** (DDD / 헥사고날 아키텍처) |
| 에이전트 | **LangGraph** 멀티 에이전트 상태 머신 (intent 분류 → 라우팅 → tool calling → 보고) |
| LLM 추론 | **Qwen3.5-2B**, **llama.cpp**(CUDA, build 9559) `:8080` reasoning-off / Ollama `:11434` |
| 파인튜닝 | **QLoRA** (4-bit NF4, PEFT) → merge → GGUF(q4_k_m) 변환 후 동일 런타임 서빙; 배포는 베이스 1개 + per-request LoRA 토글(`adapter_toggle`)로 단일화 |
| 프런트엔드 | **React + Vite** WebView 오버레이 (채팅 + 공정 대시보드 + 시뮬레이션 스튜디오) |
| 실시간 통신 | 백엔드 **SSE**(LiveTelemetryHub) 주 경로 + Firebase RTDB 보조 |
| 데이터 | PostgreSQL(세션/명령/시나리오) + Redis |
| 인프라 | Docker Compose (백엔드 스택), 호스트 Python(벤치마크·SFT·평가) |

---

## 4. 아키텍처

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │                          Operator (브라우저)                            │
 │   채팅 입력 ───────────────┐        ┌─────── 픽셀 스트리밍 영상(WebRTC)   │
 └───────────────────────────┼────────┼──────────────────────────────────┘
                             │        │
              POST /chat     │        │  iframe :8880 (player page)
                             ▼        │
 ┌───────────────────────────────────┼──────────────────────────────────┐
 │  chatbot-backend (FastAPI, DDD)    │                                   │
 │                                    │                                   │
 │  LangGraph 상태 머신                │                                   │
 │   classify_intent (LLM+keyword)    │                                   │
 │     → robot_command / process_status / compare_runs / optimize_agvs   │
 │     → general_chat / simulation_status                                │
 │   ToolRouter.validate(check_ranges) ── 9개 typed tool 검증              │
 │                                                                        │
 │  OllamaLlmGateway / LlamaCppLlmGateway  ── LLM 경계                     │
 │  Ue5CommandClient ──── POST ────────────────────►  :7777               │
 │  LiveTelemetryHub  ◄─── WS ingest ───────────────  UE5 텔레메트리        │
 │  GET /unreal/telemetry/stream (SSE) ───► 웹 대시보드                     │
 └───────────────────────────────────▲──────────────────────────────────┘
                                      │ HTTP / WebSocket
 ┌────────────────────────────────────────────────────────────────────────┐
 │  Unreal Engine 5  ·  AAGVSimController (:7777)                           │
 │   /sim/start · /sim/stop · /sim/pause · /sim/speed · /agv/command        │
 │   AGV 셀 시뮬레이션 → 이벤트/충돌 감지 → KPI(처리량·대기·충돌·병목률)        │
 │   F1 혼잡 히트맵 · F4 시나리오 검증(verdict) · 픽셀 스트리밍 송출           │
 └────────────────────────────────────────────────────────────────────────┘
```

설계 원칙:
- **경계에서만 검증** — 사용자 입력과 UE5 응답 등 시스템 경계에서만 스키마/범위 검증.
- **결정론적 코어** — KPI/병목률은 `domain/process_model.py` 단일 진실원에서 산출해 데모 재현성 확보.
- **LLM 경계 분리** — `OllamaLlmGateway`를 `LlamaCppLlmGateway`가 transport만 오버라이드해 상속 →
  추론 백엔드를 바꿔도 후처리 로직은 바이트 단위로 동일 → **모델과 시스템을 분리해 평가** 가능.

---

## 5. 주요 기능

### 5.1 에이전트 기반 시뮬레이션 제어 & 결과 확인

에이전트는 **2단계**로 동작한다. 1단계는 발화를 *어느 처리 가지*가 맡을지 정하는 **라우팅(intent routing)**,
2단계는 그 중 `robot_command` 가지에서만 일어나는 **도구 선택(tool calling)**이다. 즉 `start_simulation`
같은 *명령(tool)* 과 `process_status` 같은 *라우트(route)* 는 서로 다른 계층의 개념이다.

#### (1) 1단계 — Route Classification (어느 가지가 처리할지)

LangGraph 분류기(LLM + keyword fallback)가 발화를 다음 라우트 중 하나로 보낸다.

| 라우트 | 설명 | tool 호출? |
|---|---|---|
| `robot_command` | UE5에 실제 제어 명령을 쏘는 유일한 경로 → 2단계 tool planner로 진입 | **O** |
| `process_status` | "현재 공정 상태/처리량 알려줘" 등 읽기 전용 상태 질의 | X (전용 노드) |
| `station_action_query` | 특정 스테이션의 동작/상태를 묻는 정보성 질의 | X |
| `compare_runs` | "방금 결과랑 아까 결과 중 뭐가 나아?" → 두 런의 KPI A/B 판정 | X (결정론적) |
| `optimize_agv_count` | "병목률 5% 이하 최적 대수 찾아줘" → 목표 탐색 폐루프(agentic loop) | X (결정론적) |
| `general_chat` / `simulation_status` | 잡담·맥락 대화 / 진행 중 런의 실시간 상태 보고 | X |

`compare_runs`·`optimize_agv_count`·`process_status` 등은 tool 호출 없이 **전용 그래프 노드(결정론적 로직)**가
처리하므로 2단계로 내려가지 않는다. `robot_command` 만이 tool planner를 거친다.

#### (2) 2단계 — Tool Planning (robot_command 가지 내부)

```text
robot_command (route)
      │
      ▼
  Tool Planner LLM (최소 프롬프트 / SFT 가중치)
      │
      ▼
  {"name": "start_simulation", "arguments": {"agv_count": 3, ...}}   ← name = 9개 tool 중 택1
      │
      ▼
  ToolRouter.validate(check_ranges=True)
      │
      ├── valid command ───────► UE5 (:7777) 로 디스패치
      ├── none ────────────────► 행동하지 않음 (범위 밖/잡담)
      ├── clarify ─────────────► 운영자에게 되묻기 (정보 누락/모호)
      └── invalid / range 실패 ─► 안전 거부 (station -1, speed -2x 등 차단)
```

#### (3) 2단계 주요 tool — 운영자가 직접 호출 가능한 명령

Tool Planner는 **9개 typed tool 중 정확히 하나**를 골라 엄격한 JSON을 emit한다.

| 명령 (tool) | 동작 |
|---|---|
| `start_simulation` | 시뮬레이션 시작 (`agv_count`, `speed_multiplier`, `acceptance[]` 등 옵션) |
| `stop / pause / resume_simulation` | 정지 / 일시정지 / 재개 (런 라이프사이클 제어) |
| `set_sim_speed` | 배속 변경 (`speed_multiplier`) |
| `run_station_task` / `inspect_station` | 특정 스테이션 작업 실행 / 점검 (`station_id` 필수) |
| `cancel_command` | 진행 중 명령 취소 (`command_id`) |

추가로, 명령이 아닌 두 종단 상태로 **안전성**을 보장한다(위 ToolRouter 분기의 `none`/`clarify`).
- `none` — 범위 밖/잡담 → **행동하지 않음**
- `clarify` — 정보 누락/모호/유효하지 않은 입력 → **추측하지 말고 되묻기**

> 참고: `move_to_station` 은 충돌·오작동 위험 때문에 사용자 직접 호출에서 제외하고 에이전트 내부 계획용으로만 유지한다(9개 tool에는 포함).

#### (4) 명령 접수 시 에이전트 동작 과정

**예시 A — "AGV 3대로 2배속 시뮬레이션해줘" (단일 명령형)**

```
1. classify_intent : LLM 분류기(+keyword fallback)가 robot_command 로 라우팅
                     (sim 토픽어 + lifecycle 동사 → llm_guard 로 오분류 교정)
2. propose_tool_call: start_simulation { agv_count:3, speed_multiplier:2.0 }
3. ToolRouter.validate(check_ranges=True): 대수/배속 범위 검증
4. (acceptance 없으면) 셀 최대 AGV 대수를 UE5 /sim/status 에서 실시간 조회
5. Ue5CommandClient → POST /sim/start  ── 실패 시 정직하게 FAILED 보고(가짜 성공 금지)
6. plan 스트리밍: "분석 → 설정 확정 → AGV 투입" 3스텝을 단계별로 노출
7. UE5 → 텔레메트리/완료 이벤트 → ReportAgent 가 KPI + 합격/불합격(verdict) 요약
```

**예시 B — "병목률 5% 이하의 최적 AGV 대수를 찾아줘" (목표 탐색형 / agentic loop)**

여기서 에이전트는 일회성 명령 실행기가 아니라 **목표 탐색 에이전트**로 동작한다.

```
1. _is_optimize_request 사전 판정 → optimize_agv_count 노드 (LLM 없이 결정론적)
2. parse_optimization_goal : "병목률 ≤ 5%" 를 (metric, comparator, threshold) 로 파싱
3. UE5 /sim/status 로 셀에 배치된 최대 AGV 대수 조회 (탐색 상한)
4. search_optimal_agv_count : observe → judge → decide → re-run 폐루프
     - 후보 대수마다 process_model.simulate_run_kpis(n) 로 KPI + 병목률 산출
       (병목률 = 혼잡 히트맵 그리드에서 피크 밀도 60% 이상 셀의 비율)
     - 각 후보를 실제 Simulation + SimulationRun 으로 영속화 → 실행 기록에 노출
     - 목표를 만족하는 "가장 높은(=가장 여유 있는)" 대수에서 정지
5. 시도한 모든 대수와 선택된 최적값을 한국어 리포트로 반환 (재현 가능)
```

병목률을 결정론적 모델(`process_model`)로 산출해 두어, UE5 왕복 없이도 매 후보를 즉시 평가할 수 있고
데모가 100% 재현 가능하다 — 이는 "프로토타입은 속도 우선" 원칙과 정확히 부합한다.

#### (4-1) 시뮬레이션 결과 지표 (KPI)

두 예시 모두 런이 끝나면 동일한 KPI 집합이 산출된다. 이 지표들은 UE5 `AAGVSimController`가
실시간으로 계산해 `kpis`로 emit하며, 동시에 `ProcessTelemetry` 프레임으로 라이브 스트리밍된다.

| KPI | 정의 | 방향 |
|---|---|---|
| **처리량 (throughput)** | 시간당 완료된 Load→Unload 운반 사이클 수 (대/h) | 높을수록 ↑ |
| **평균 대기 (avg_wait_time)** | AGV가 교차로/스테이션에서 대기한 평균 시간(초) | 낮을수록 ↑ |
| **충돌 (collision_risk / collision_count)** | 런 동안 누적된 AGV 간 근접·충돌 횟수 | 낮을수록(0건) ↑ |
| **가동률 (uptime)** | 전체 시간 중 AGV가 실제 작업한 비율(%) = 셀 work rate | 높을수록 ↑ |
| **병목률 (bottleneck_rate)** | 혼잡 히트맵 그리드에서 피크 밀도 60% 이상인 "hot" 셀의 비율(%) | 낮을수록 ↑ |
| **가동 AGV (active_agvs)** | 현재 실제로 운행 중인 AGV 대수 | — |

이 6개 지표가 **예시 A와 B에서 서로 다르게 소비된다**는 점이 핵심이다.

- **예시 A (단일 명령형 → verdict).** acceptance 기준을 걸면(예: "처리량 ≥ 70/h, 평균 대기 ≤ 12s,
  충돌 0건") F4 `UScenarioVerificationComponent`가 위 KPI를 각 기준과 대조해 **per-criterion PASS/FAIL
  + 전체 verdict**를 산출한다. ReportAgent는 단순 수치가 아니라
  *"PASS — 처리량 74.9/h, 대기 11.4s. 단 충돌 1건 → 안전성 FAIL. 우선순위 적재 정책 권장"* 식으로 보고한다.
  → KPI가 **합격/불합격 판정의 입력**으로 쓰인다.

- **예시 B (목표 탐색형 → 비교·선택).** 후보 대수마다 동일 KPI 집합을 산출하되, 목표 지표
  (**병목률**)를 임계값과 비교해 만족 여부를 판정한다. 폐루프는 n=1·2·3…의 병목률을 나열하고
  목표를 만족하는 최적 대수를 고른다(병목률은 AGV 대수에 단조 증가하도록 캘리브레이션 — n=1≈13%,
  n=2≈24%, n=3≈39%). → KPI(특히 병목률)가 **후보 간 탐색·선택의 목적함수**로 쓰인다.

즉 같은 KPI라도 예시 A에서는 "기준 충족 검증(verdict)", 예시 B에서는 "후보 비교 목적함수"로 역할이 달라진다.
이것이 에이전트가 단순 명령 실행기를 넘어 **실험을 설계·검증하는 주체**가 되는 지점이다.

#### (5) 시뮬레이션 결과 확인

- **혼잡 히트맵 / 병목률** — UE5의 `UCongestionHeatmapComponent`가 AGV 위치를 ~10Hz로 샘플링해
  바닥에 실시간 밀도 히트맵을 렌더링한다. 교차로에 차량이 몰리면 KPI 표가 갱신되기 *전에* 바닥이
  붉게 물들어 병목이 형성되는 순간을 시각적으로 보여준다. 동일 밀도 그리드에서 병목률 KPI가 파생된다.
- **결과 리포트 & A/B 비교** — 런 종료 시 처리량/대기/충돌/가동률/병목률을 집계하고,
  "방금 결과랑 아까 결과 중 뭐가 나아?"라는 질문에 `compare_runs` 라우트가 KPI별 승패를 집계해
  결정론적 판정을 반환한다. 합격 기준(acceptance)을 건 런은 PASS/FAIL verdict이 우선한다.
- **시뮬레이션 스튜디오** — 좌측 사이드 탭에서 시나리오 목록·실행 기록(과거 런 KPI)을 보고,
  우측 패널에서 설정·재생·배속을 제어한다. **챗봇으로 시작한 런과 패널로 시작한 런이 하나의
  시나리오/런 저장소로 통합**되어, 채팅으로 만든 시나리오도 스튜디오에서 다시 실행·비교할 수 있다.

#### (6) AGV 행동 설계 — UE5 StateTree

위 KPI를 만들어내는 AGV 한 대 한 대의 자율 행동은 **UE5 StateTree**로 설계했다. 채팅 에이전트가
"무엇을 할지(어떤 시뮬레이션을 돌릴지)"를 정하는 1·2단계 라우팅/도구 계층이라면, StateTree는
개별 AGV가 "운반 작업을 어떤 순서로 수행할지"를 결정하는 **현장 실행 계층**이다.

**설계 원칙 — 작업 시퀀싱과 저수준 실행의 분리.**
`UAGVTaskComponent`가 `UStateTreeComponent`를 보유하고 `LifecycleStateTree` 에셋을 구동한다
(`SetStartLogicAutomatically(false)` → 컨트롤러가 명시적으로 `StartLogic`). 각 StateTree task는
얇은 C++ 래퍼로, **AGV의 내부 상태(`EAGVState`) 진입을 *요청*하고 그 진행 상황을 `Running/Succeeded/
Failed`로 트리에 보고**할 뿐이다. 실제 이동·물리·충돌 처리는 `AAGVActor` + `UAGVMovementComponent`가
소유한다. 즉 **StateTree = 작업 결정/순서, Actor = 실행** 으로 책임이 분리된다. 컨트롤러는
`SendStateTreeEvent(EventTag)` 로 트리에 외부 이벤트(취소·충돌 등)를 주입한다.

**작업 라이프사이클(텍스트 아키텍처).** 한 운반 주문(order)은 다음 task 시퀀스로 흐른다.

```text
StateTree (LifecycleStateTree)
   │
   ▼
[Reserve Route Segment] ── 교차로/구간 점유권 확보까지 대기(WaitingAtSection)
   │   (점유권 확보 → Succeeded)
   ▼
[Move Along Spline To Target] (MovementState = MovingToPickup) ── 적재지로 스플라인 주행
   │
   ▼
[Load Cargo] ── 적재(Loading) 수행
   │
   ▼
[Reserve Route Segment] → [Move Along Spline To Target] (MovingToDropoff) ── 하역지로 주행
   │
   ▼
[Unload Cargo] ── 하역(Unloading) 수행
   │
   ▼
[Complete Order] ── 주문 완료 처리 → Idle 로 복귀, 다음 주문 수령
        └─(이상 시)─► [Fail Order] ── 사유와 함께 주문 중단(충돌 등)
```

**각 task 설명** (`Source/VCORE/.../StateTree/`):

| Task | 역할 | 반환 규칙 |
|---|---|---|
| **Reserve Route Segment** (`FAGVReserveRouteSegmentTask`) | 다음 경로 구간/교차로의 점유권을 확보하는 게이트. AGV가 `IsWaitingForRoute()`(대기 중)이면 진행을 막는다 | 대기 중 → `Running`, 점유권 확보 → `Succeeded` |
| **Move Along Spline To Target** (`FAGVMoveAlongSplineToTargetTask`) | 파라미터 `MovementState`(MovingToPickup/Dropoff/Station)로 지정된 목표까지 스플라인 주행을 요청 | 주행 중 → `Running`, 도착 → `Succeeded` |
| **Load Cargo** (`FAGVLoadCargoTask`) | 적재지 도착 후 `Loading` 상태 진입을 요청 | 적재 중 → `Running`, 완료 → `Succeeded` |
| **Wait At Station** (`FAGVWaitAtStationTask`) | 스테이션에서 `DurationSeconds` 만큼 정차(작업/검사 시간 모사). `RemainingSeconds` 를 틱마다 감소 | 잔여>0 → `Running`, 0 → `Succeeded` |
| **Unload Cargo** (`FAGVUnloadCargoTask`) | 하역지 도착 후 `Unloading` 상태 진입을 요청 | 하역 중 → `Running`, 완료 → `Succeeded` |
| **Complete Order** (`FAGVCompleteOrderTask`) | `CompleteStateTreeOrder()` — 주문을 정상 완료로 마킹하고 다음 주문을 받을 수 있게 함 | 완료 → `Succeeded`, 실패 → `Failed` |
| **Fail Order** (`FAGVFailOrderTask`) | `FailStateTreeOrder(FailureReason)` — 충돌 등으로 주문을 사유와 함께 중단 | 처리됨 → `Succeeded`, 실패 → `Failed` |

모든 task는 `FAGVStateTreeTaskBase`를 상속하고 `Input` 핀으로 대상 `AAGVActor`를 받는다(`ResolveAGV`).
이 구조 덕분에 새로운 운반 정책(예: 우선순위 적재, 검사 경유)은 **C++ 재작성 없이 StateTree 에셋에서
task를 재배열**하는 것으로 표현되며, 충돌·취소 같은 예외는 이벤트 주입(`SendStateTreeEvent`)으로
어느 task 단계에서든 `Fail Order`로 분기할 수 있다. `EAGVState`(Idle·MovingToPickup·Loading·
MovingToDropoff·Unloading·WaitingAtSection·MovingToStation·StoppedCollision·StoppedOperation)는
이 task들이 요청·관측하는 단일 상태 어휘로, 텔레메트리·HUD·KPI 집계가 모두 같은 enum을 공유한다.

---

### 5.2 온프레미스 추론 엔진 & 프롬프트 증류 파인튜닝

> 이 절은 **무엇을 만들었는가**(온프레미스 추론 서빙 + 프롬프트 증류 모델)를 *기능*으로 기술한다.
> 이 구성에 **왜·어떻게** 도달했는지 — Ollama vs llama.cpp 벤치마크, Validation Layer 검증, fine-tuning
> 필요성 판단 — 는 *문제 해결 과정*이므로 6장(평가 체계)·7장(문제 해결)에서 다룬다.

#### 추론 엔진

데이터 통제·비용 문제로 시스템은 **완전 온프레미스**로 동작한다(호스팅 LLM API 없음).
프로덕션 모델은 **Qwen3.5-2B**이며, 두 가지 방식으로 서빙한다.

- **llama.cpp (CUDA build 9559)** — `:8080`, `--reasoning off`, `-ngl 99`.
  reasoning-off는 단일 최대 latency 레버로, disambiguation 경로를 **~11.7s → ~2.4s**로 단축했다.
- **Ollama** — `:11434`, 동일 GGUF blob.

> 왜 llama.cpp reasoning-off를 택했는지 — Ollama와의 벤치마크 비교, CUDA 재빌드로 잡은 latency 회귀 —
> 는 기능이 아니라 *문제 해결 과정*이므로 [7.2](#72-fine-tuning이-필요한-상황인가를-가르는-벤치마크-검토)에서 다룬다.

#### 파인튜닝 — "프롬프트 증류 (Prompt Distillation)"

프로덕션 정확도(94% KPI / 91.7% disambiguation)는 **길고 정교하게 손튜닝한 시스템 프롬프트**에
의존하고 있었다. 즉 **역량이 가중치가 아니라 프롬프트 문자열에 있었다.** 이는 유지보수성(도구 추가마다
프롬프트 수정), 확장성(도구 수에 비례해 프롬프트 증가), 추론 비용(매 턴 긴 프롬프트 재인코딩),
견고성(reasoning-off에서 깊은 지시 스택의 준수도 저하)이라는 구조적 부채였다.

이를 **QLoRA로 가중치에 내재화(증류)**해, 4줄 최소 프롬프트만으로도 라우팅이 동작하도록 했다.

- **데이터**: 450행(Train 300 / Val 50 / Test 100). 9개 실제 도구(`tools/contracts.py`)에 grounding,
  모든 라벨을 live `ToolRouter.validate`로 검증(450/450 valid). 템플릿+슬롯 확장으로 label-by-construction
  → 라벨 노이즈 0. Test는 프롬프트 문자열 중복 0(450/450 unique)으로 누수 차단.
- **학습**: `Qwen/Qwen3.5-2B`(프로덕션과 동일 베이스), 4-bit NF4, LoRA r=16/α=32,
  completion-only loss(프롬프트 토큰 마스킹 → 프롬프트 echo가 아닌 출력 생성을 학습).
  trainable 10.9M(0.58%), RTX 4060 Ti 8GB **~7분**, eval-loss 0.0315 → 0.0037 → 0.0029(단조 수렴).
- **배포**: adapter → merge(fp16) → GGUF(f16) → q4_k_m(1.27GB) → **베이스와 동일한 llama.cpp/플래그**로 서빙.

#### 주요 결과 (3-조건 held-out 평가, n=100, 동일 서버)

| 조건 | 가중치 | 프롬프트 | Tool-routing 성공률 |
|---|---|---|---:|
| Base + Minimal | 프로덕션 베이스 | 4줄 | **12%** |
| Base + Full | 프로덕션 베이스 | 긴 운영 프롬프트 | **49%** |
| **SFT + Minimal** | 파인튜닝 | 4줄 | **96%** |

- **SFT+Minimal(96%)은 Base+Full(49%)의 약 2배, Base+Minimal(12%)의 8배.**
  라우팅 역량이 **프롬프트가 아니라 가중치에** 있음을 입증.
- 핵심 카테고리: disambiguation 30→**95%**, kpi_acceptance 50→**100%**, 파라미터 거부 규율(invalid/missing) 0→**100%**.
- **프롬프트 의존도**: 베이스는 프롬프트 제거 시 49→12(−37pp) 붕괴하나, SFT는 96 유지(잃을 의존이 없음).
- 정직한 trade-off: `run_station_task` 100→90%(1/10)만 Base+Full 미만 — gate 항목 아니며 다른 큰 이득으로 상쇄.

> 정량적 검증을 통해 fine-tuning이 *정확도* 목적으로는 불필요함을 먼저 입증한 뒤(7.2 참조),
> SFT의 목표를 "정확도 향상"이 아니라 **"프롬프트 의존 제거(증류)"**로 재정의한 것이 이 트랙의 핵심 판단이다.

#### 배포 진화 — 단일 모델 통합 (8GB VRAM 제약 → Adapter Toggle)

> 위 증류 SFT는 "라우팅을 가중치로 옮길 수 있는가"를 입증했다(tool-routing 49→96%). 그 위에서
> **실제 배포 형상**을 한 번 더 정리한 것이 이 절이다 — 역할이 다른 두 모델을 한 모델로 접는 과정.

**문제 — 두 모델이 8GB VRAM에 동시에 올라가지 않는다.**
초기 배포(`routing_split`)는 역할이 다른 **두 개의 물리 모델**을 동시에 띄웠다:
① tool-routing SFT GGUF를 llama.cpp에, ② 대화·계획·보고용 베이스(`qwen3.5:2b`)를 Ollama에.
"라우팅은 SFT, 대화·보고는 베이스"라는 역할 분리 자체는 옳았지만(증류 SFT는 라우팅 전용으로 좁혔으므로
일반 생성을 맡길 수 없다), 그 분리를 **두 모델 인스턴스**로 구현하니 RTX 4060 Ti **8GB** 예산을 초과했다.

**1차 시도 — 통합 path/action SFT 하나로 전부 덮을 수 있나?**
먼저 route(어느 가지) + action(어느 tool)을 **한 모델이 동시에 선택**하는 통합 SFT를 학습했다
(748행, QLoRA r=16/α=32). 제어 평면 성능은 강력했다 — 베이스 대비 route 45.2→**100%**,
full-decision 38.6→**99.4%**, false-positive action 4.2→**0%**. 그렇다면 이 SFT 하나로 대화·보고까지
덮으면 모델이 자연히 하나로 줄지 않을까?

**그러나 — 측정이 본능을 다시 막았다.**
이 SFT를 **실제 백엔드 경로**(`LlamaCppLlmGateway.generate_report`/`generate_chat_response`, 프로덕션
템플릿)로 대화·보고 각 4건을 베이스와 대조하자, 라우팅 전용으로 증류된 모델은 일반 생성에서 두 가지
결함을 냈다: ① **본문 verbatim 중복**(보고서 전체가 두 번 렌더), ② **언어 누출**(한국어 인사에 중국어
토큰 혼입). → "단일 SFT로 전부"는 데모에서 드러날 결함이라 **drop-in 불가**로 판정 — 역할 분리는
여전히 필요했다.

**최종 — Adapter Toggle (한 베이스 + per-request 토글되는 LoRA, 엔드포인트 1개).**
그래서 두 모델 대신 **베이스 1개 + 라우팅 LoRA 어댑터(~22MB)를 같은 llama.cpp 엔드포인트에 얹고,
요청마다 어댑터 스케일을 토글**한다 — 라우팅 호출은 scale 1.0(증류된 라우터), 대화·보고·계획 호출은
scale 0.0(결함 없는 순수 베이스). 프로젝트 llama.cpp(build 9559)는 요청 바디의
`"lora":[{"id":0,"scale":N}]`를 해당 슬롯에만 적용하므로, 0.0 대화 호출과 1.0 라우팅 호출이 서로
간섭하지 않는다. 이로써 `routing_split`의 두 물리 모델이 **VRAM에 상주하는 베이스 1개 + 22MB 어댑터**로
접힌다(`LLM_PROVIDER=adapter_toggle`, `RoutingSplitLlmGateway(general=base@0.0, routing=router@1.0)`).

| 기능 | 어댑터 scale | 결과 |
|---|---|---:|
| 라우팅 (route+action, 166 케이스) | 1.0 | **99.4%** (165/166; 단일 오류는 `agv_count`→`ag_count` 키 오타 1건) |
| 보고서 (4건) | 0.0 | **결함 0** (중복·언어 누출 없음), ~2.5–3.1s |
| 대화 (4건) | 0.0 | **결함 0**, ~1.7–2.5s |

통합 게이트웨이를 통한 라우팅이 standalone SFT eval(99.4%)과 일치하고, all-SFT 테스트에서 나타났던
대화/보고 결함은 그 경로가 순수 베이스로 도는 덕에 사라진다. 백엔드 단위테스트 32건 통과.

> 교훈: **모델을 줄이는 것과 역량을 줄이는 것은 다르다.** "단일 SFT로 전부"라는 매력적인 단순화는
> 측정으로 기각하고(대화/보고 결함), 대신 한 베이스 위에서 LoRA를 per-request로 토글해 *두 모델의 역할
> 분리는 유지한 채 물리 모델만 하나로* 접었다 — 8GB 예산 안에서 라우팅 99.4%와 무결점 대화·보고를
> 동시에 얻었다.



---

## 6. LLM 평가 체계 (Evaluation Methodology)

이 프로젝트의 모든 LLM 의사결정은 "느낌"이 아니라 **재현 가능한 평가 하네스**의 수치로 방어된다.
평가 체계 자체를 단계적으로 설계·발전시킨 과정은 다음과 같다.

### 6.1 평가가 풀어야 했던 질문

추론 백엔드(Ollama vs llama.cpp) 교체를 검토하면서, 단순 latency 비교로는 답할 수 없는 4개 질문을 정의했다.

1. 어떤 Provider가 더 안정적으로 Tool Calling을 수행하는가?
2. JSON 구조화 출력은 얼마나 안정적인가?
3. Validation Layer는 실제로 도움이 되는가?
4. **Fine-tuning이 필요한 상황인가?**

핵심 설계 철학: **"모델 성능"과 "시스템 성능"을 분리해서 측정한다.** 둘을 뭉뚱그리면 엉뚱한 레이어를 고치게 된다.

### 6.2 Phase 1 — 스모크 테스트와 그 한계 (왜 v2가 필요했나)

초기 하네스는 12개 프롬프트로 Ollama vs llama.cpp를 비교했다(JSON 91.7% vs 58.3%, tool 정확도 66.7% vs 91.7%).
하지만 이 결과를 **결론으로 쓸 수 없다**는 것을 먼저 비판적으로 규명했다.

- **해상도 바닥**: n=12면 1프롬프트 = 8.33pp. "91.7% vs 58.3%"는 단 **4개 프롬프트** 차이.
- **신뢰구간 중첩**: 58.3%@n=12의 Wilson 95% CI는 약 [32%, 81%] → 어떤 순위도 통계적으로 성립하지 않음.
- **카테고리당 n=1**: `set_speed`/`run_station_task`/KPI는 단일 샘플 → flake 하나로 100%↔0% 반전.
- **반복 없음**: temperature>0 로컬 LLM은 비결정적인데 각 프롬프트를 1회만 실행 → 모델 오류와 런-노이즈 분리 불가.
- **인자 미채점(치명적)**: *어떤 tool*을 골랐는지만 보고 *인자가 맞는지*는 안 봄 → 잘못된 인자가 PASS로 집계.

→ Phase 1은 "하네스가 동작함"의 검증일 뿐, 신뢰성 순위의 근거가 될 수 없다고 결론. 12개 약점(W1~W12)을 표로 정리해
v2 설계의 요구사항으로 전환했다.

### 6.3 Benchmark v2 — 신뢰성 있는 평가 스위트 설계

| 설계 요소 | 내용 |
|---|---|
| **규모** | 133 케이스 × 12 카테고리, 카테고리당 ≥10 (flake가 카테고리를 뒤집지 못하게) |
| **이중언어** | 한국어 + 영어 (제품이 한국어 대면) |
| **인자 단위 채점** | `(tool_correct, args_correct, json_ok, schema_ok)` 튜플 — Phase 1의 W3 결함 해소 |
| **반복** | 각 케이스 **R=5회** → 안정적 비율 + 진짜 분산 추정 |
| **생성 방식** | 템플릿 + 슬롯 확장으로 JSONL 생성 → 라벨이 *구성에 의해* 정답(label-by-construction), 모델 출력에서 긁지 않음 |
| **버전 관리** | 정적 JSONL을 커밋 → 런타임 생성 금지, 결과 재현 보장 |

**12개 카테고리**: positive invocation · negative control · ambiguous · 단일 파라미터 추출 · 다중 파라미터 추출 ·
missing parameter · long natural language · KPI/acceptance(중첩 배열) · invalid parameter · **disambiguation(verb→tool)** ·
sequential workflow · state-dependent. 거부(decline)·모호·누락·무효 케이스를 충분히 넣어 "행동하지 않아야 할 때
행동하지 않는가"까지 측정하도록 했다.

**Task Success Rate** = `tool_correct AND args_correct AND (schema_ok OR 허용 가능한 fallback)` —
"에이전트가 실제로 옳은 일을 했는가"를 반영하는 단일 헤드라인 지표로 정의했다.

### 6.4 2×2 Ablation — 모델과 시스템을 분리

프로덕션 경로는 "모델 호출"이 아니라 **Validation Layer**(JSON 추출 → 스키마 검증 → repair retry →
결정론적 rule-based fallback)다. Phase 1은 모델 본연 능력과 이 스캐폴딩을 혼동했다. 그래서 레이어를
**ablatable**하게 만들고(생성자 토글: `structured_retry_count=0`, `enable_rule_based_fallback=False`) 2×2로 분리했다.

| | Provider only (intrinsic) | Provider + Validation Layer (production) |
|---|---|---|
| **Ollama** | A1 | A2 |
| **llama.cpp** | B1 | B2 |

`LlamaCppLlmGateway`가 `OllamaLlmGateway`를 상속해 transport만 오버라이드하므로 **레이어 로직은 두 Provider에
바이트 단위로 동일** → ablation이 "레이어가 Provider별로 무엇을 사주는가" 단 하나만 분리한다.
규모: 133 × R5 × 4셀 = **2,660회 채점** (재시도 포함 ~2,860 LLM 호출).

### 6.5 Wilson 신뢰구간 — 과장하지 않기

모든 비율에 **Wilson 95% CI**를 붙이고, **CI가 분리될 때만 주장**한다. 이것이 일화를 발견으로 바꾼 장치다.

| 셀 | Task Success | 95% CI | k/n |
|---|---|---|---|
| A1 Ollama OFF | 75.6% | [72.2–78.8] | 503/665 |
| A2 Ollama ON | 75.9% | [72.6–79.0] | 505/665 |
| B1 llama.cpp OFF | 69.0% | [65.4–72.4] | 459/665 |
| B2 llama.cpp ON | 74.0% | [70.5–77.2] | 492/665 |

→ A1≈A2 완전 중첩 → 레이어는 Ollama에 **통계적으로 중립**. B1 vs B2 비중첩 → llama.cpp엔 **진짜 +5.0pp**.
구간이 직접 판정하므로 손짓(hand-waving)이 필요 없다.

### 6.6 실험 통제 (공정성·재현성)

- 동일 GGUF blob·동일 디코드 파라미터(`num_ctx 2048`), 두 Provider는 **한 번에 하나만** 서빙(VRAM 경합 차단).
- 시드 고정 불가한 런타임이므로 **R≥5 반복 후 평균±CI** 보고 (로컬 샘플링이 지배적 노이즈원).
- 반복마다 프롬프트 순서 무작위화(캐시 순서 편향 제거), cold/warm latency 분리 보고.
- **사전 등록(pre-registration)**: v2 케이스·지표 정의·가설을 실행 *전에* 동결 → 카테고리 p-hacking 방지.

### 6.7 사전 등록된 의사결정 규칙 (fine-tuning 게이트)

평가는 단순 점수표가 아니라 **결정을 내리기 위한 도구**였다. 실행 전에 분기 규칙을 못 박았다.

- A2/B2 ≈ A1/B1 (레이어 효과 미미) → 베이스 모델이 충분 → **fine-tuning 생략**, 프롬프트/스키마에 투자.
- A2/B2 ≫ A1/B1 이고 lift가 대부분 **fallback** → 제품이 결정론적 코드에 업혀 있음 → 정직하게 문서화.
- A1/B1에서도 1차 스키마 성공률이 낮고 fallback이 하드 카테고리를 못 덮음 → **fine-tuning 정당화** → Phase 3.

실제로는 **첫 번째 분기**가 발동(A1≈A2)했고, 수정 후 JSON parse 100% / 1차 스키마 94%에 도달해
"포맷 병목" 가설이 사망 → fine-tuning의 원래 근거가 무효화됐다. 남은 것은 의미론적 잔여 2개
(kpi_acceptance, disambiguation)뿐이었고, 이를 Phase 2.5(가장 싼 레버)로 먼저 공략했다(상세 7.2).

### 6.8 SFT 평가 — 3-조건 A/B/C 매트릭스

파인튜닝(프롬프트 증류)의 효과는 별도 평가 설계로 검증했다. 동일 llama.cpp `:8080`, 동일 채점기,
동일 held-out 100행에서 **가중치와 프롬프트만 변수**로 둔다.

| 조건 | 가중치 | 프롬프트 | 분리하는 것 |
|---|---|---|---|
| Base + Full | 프로덕션 베이스 | 긴 운영 프롬프트 | 현행 운영 기준 |
| Base + Minimal | 프로덕션 베이스 | 4줄 | 긴 프롬프트가 떠받치던 양 |
| SFT + Minimal | 파인튜닝 | 4줄 | 라우팅이 가중치로 들어갔는가 |

누수 방지: test split은 train/val과 **프롬프트 문자열 중복 0**(450/450 unique)으로 동결.
결과는 12% / 49% / 96% — 프롬프트 의존(−37pp) 제거를 입증(상세 5.2).

이 평가 체계 전체(Phase 1 → 2 → 2.5 → 3)가 곧 아래 7장의 기술적 문제 해결 과정의 기반이 된다.

---

## 7. 기술적 문제 및 해결

세 문제는 **발견 순서대로** 읽으면 인과가 분명해진다. 평가 하네스(6장)로 2×2 ablation을 돌리자
**운영 중이던 Validation Layer가 최고 모델을 악화**시키고 있었고(7.1), 이를 고치자 "포맷 병목" 가설이
죽으며 **fine-tuning의 원래 근거가 무효화**됐다. 그 위에서 "정말 fine-tuning이 필요한가"를 벤치마크로
다시 따져, 프롬프트 2줄·llama.cpp reasoning-off 서빙이라는 **무료 레버로 정확도 과제를 해소**(7.2)했다.
즉 **Validation Layer(7.1)가 llama.cpp 벤치마크 판단(7.2)보다 먼저** 온다 — 전자가 후자의 전제를 깔기
때문이다(7.1을 고치기 전엔 disambiguation이 모델 한계인지 시스템 결함인지 가릴 수 없었다). 마지막
7.3은 LLM과 무관한 영상 파이프라인 장애다.

### 7.1 Validation Layer가 최고 성능 모델을 오히려 악화

> 참조: [docs/decisions/benchmark_phase2_validationlayer.md](decisions/benchmark_phase2_validationlayer.md)

**Problem.**
초기 가설은 "JSON Repair / Retry / Fallback 후처리 레이어를 붙이면 모든 Provider 품질이 향상된다"였다.
이를 검증하려 Validation Layer를 ablatable하게 만들고 2×2(Ollama/llama.cpp × Layer OFF/ON) 대규모
ablation(133 케이스 × R5 × 4셀 = 2,660회)을 수행했는데, 결과는 가설과 정반대였다.
**Ollama는 Layer 적용 시 Task Success가 75.2% → 54.3%로 −21pp 악화**했다(반면 llama.cpp는 향상).
즉 "프로덕션에 배포된 경로(A2)가 아무것도 안 한 것(A1)보다 나빴다."

**Solution.**
카테고리별 채점으로 원인을 분리했다. 악화는 모델 결함이 아니라 **시스템 결함**이었다.
- **Repair-retry 프롬프트 결함** — 재시도 프롬프트가 "반드시 하나의 유효한 tool을 출력하라"는 형태라,
  *원래 거부(decline)해야 할 입력*에서도 강제로 tool을 환각 생성했다. negative_control 94.3% → 2.9%,
  ambiguous 86.0% → 0.0%로 붕괴. → 거부를 종단 상태로 인정하도록 3단계(sentinel 추가 → 재시도 중단 →
  clean decline을 terminal로) 반복 수정.
- **Validator range-check 부재** — 타입만 검사하고 범위를 검사하지 않아 `station -1`, `speed -2x`가
  UE5로 그대로 흘렀다. → 범위 검증 추가로 invalid_parameter ~4% → ~57%.

**Result.**
수정 후 A2는 **54.3% → 75.9% (Wilson CI 비중첩, +21.6pp)**, JSON parse 100% / 1차 스키마 유효 94%.
"포맷 문제"가 해소되며 **fine-tuning을 정당화하던 근거 자체가 무효화**되었고, 의미론적 잔여 과제
(kpi_acceptance, disambiguation) 두 개만 남았다.
> 교훈: **모델 성능과 시스템 성능은 분리해 평가해야 한다.** 동일한 후처리 로직이 모델 특성(eager vs
> conservative, JSON-capable vs JSON-weak)에 따라 정반대 결과를 낸다.

### 7.2 "Fine-tuning이 필요한 상황인가"를 가르는 벤치마크 검토

> 참조: [docs/benchmark](benchmark/), [docs/sft](sft/)

**Problem.**
n=12 스모크 테스트("91.7% vs 58.3%")는 단 4개 프롬프트 차이라 어떤 주장도 뒷받침할 수 없었다.
또한 기존 하네스는 *어떤 tool을 골랐는지*만 보고 *인자가 맞는지*는 보지 않아, 잘못된 인자가 조용히
PASS로 집계됐다. 이 상태에서 "2B 모델이 약하니 fine-tune하자"는 본능은 검증되지 않은 가정이었다.

**Solution — 실험 및 사고 과정.**
- **Benchmark v2**: 133 라벨 케이스 × 12 카테고리, 한·영 병행, **argument-level 채점**, R=5 →
  2,660회 채점. 골드 라벨은 생성기로 *구성*(모델 출력에서 긁지 않음) → base 비교가 정직.
- **Wilson 95% CI**: 모든 비율에 신뢰구간을 붙이고, **CI가 분리될 때만 주장**. (A1≈A2 중첩 → 레이어는
  Ollama에 통계적 중립; B1 vs B2 비중첩 → llama.cpp엔 진짜 +5pp.) 일화를 발견으로 바꾼 장치.
- **가장 싼 레버부터** (Phase 2.5): kpi_acceptance는 fine-tuning 교과서 사례처럼 보였으나, 시스템
  프롬프트가 `acceptance` 배열을 *언급조차 안 함*을 확인. 골드 값 누출 없이 **평문 2줄**(metric/comparator
  enum + 구문 매핑) 추가만으로 **20% → 92% (CI 비중첩, +72pp)**, 전체 suite에서 **22% → 94%**.
- **서빙 진단**: disambiguation은 프롬프트로 안 움직였으나(58→60%), *동일 GGUF blob*이 reasoning-off
  llama.cpp에서 80% vs Ollama 60%로 20pt 차이 → **capability 한계가 아니라 serving artifact**.
  llama.cpp를 CUDA로 재빌드하고 reasoning-off로 서빙 → **63% → 91.7% (+28pp, 동일 가중치)**.

**Result.**
정확도 관점에서 두 잔여 과제가 모두 **무료 레버**(프롬프트 2줄, 서빙 플래그 1개)로 해소되어,
정확도 목적의 LoRA SFT는 **불필요**로 판정·종료했다. 이후 SFT는 목표를 **프롬프트 증류**로 재정의해
진행 — held-out tool-routing **49% → 96%**, 긴 프롬프트 의존(−37pp)을 제거했다(상세 5.2).
> 교훈: 문제를 만나면 즉시 모델 교체/fine-tune로 가는 게 아니라, **정량 벤치마크와 ablation으로
> 문제의 위치(모델 vs 시스템)와 개선 비용 대비 효과를 먼저 검증**한다. 불필요한 GPU-주(週) 비용을
> 줄이고 ROI 높은 방향을 식별할 수 있었다.

### 7.3 웹 뷰포트 "DISCONNECTED" — 영상은 멀쩡, 브라우저만 죽음

> 참조: [docs/troubleshooting](troubleshooting/)

**Problem.**
채팅으로 시작한 시뮬레이션이 UE5 standalone 창에서는 정상 렌더링되는데, 웹 뷰포트(`:5199`)는
"DISCONNECTED. CLICK TO RESTART" 오버레이만 띄우고 영상이 끝까지 안 나왔다.

**Solution.**
추측 대신 파이프라인을 hop 단위로 확인했다. `:7777/:8880/:8888` 모두 LISTEN, 플레이어 페이지 200,
UE 스트리머는 시그널링(`:8888`)에 ESTABLISHED. **결정적 증거는 시그널링 로그** — 스트리머 ping/pong은
꾸준한데 **플레이어 연결 이벤트가 세션 내내 0건**이었다. 즉 서버는 멀쩡, 브라우저 플레이어가 문제.
근본 원인: 임베디드 플레이어가 `MaxReconnectAttempts`(기본 3) 소진 후 영구 포기. UE가 맵 로드에
~20초 걸리는 동안 iframe이 3회를 다 써버리고 다시는 재시도하지 않았다.
- 수정: iframe URL에 `MaxReconnectAttempts=999`로 스트리머가 뜰 때까지 재시도.
- 후속(검은 화면+재생 버튼): `-AudioMixer`로 오디오 트랙이 실려 브라우저 autoplay 차단 → `StartVideoMuted=true`
  강제. 플레이어 플래그를 `App.tsx` 단일 선언 소스로 통합해 재발 방지.

**Result.**
하드 리프레시 후 뷰포트가 스스로 연결되고(수동 클릭 불필요), 시그널링 로그에 플레이어 연결 +
WebRTC 협상(offer/answer/ICE)이 기록됨. 더불어 런 종료 시 HUD가 마지막 프레임에 얼어붙던 문제도
SSE idle 분기에서 명시적 reset 프레임(`agvs:[]`, `process:{running:false}`, `hud:null`)을 push해 해결.
관련 zone 카메라 미전환 문제는 카메라가 별도 스트리밍 레벨에 있어 클릭 시점에 미로드였던 것 →
`TSoftObjectPtr` + `LoadStreamLevel` 후 재시도로 해결.
> 교훈: 분산 파이프라인 장애는 **각 hop을 측정해 책임 소재를 좁혀라.** "영상이 안 나온다"는 증상의
> 범인은 서버가 아니라 클라이언트의 재시도 정책이었다 — 로그가 가설을 이겼다.

---

## 8. 결과

### 결론 및 주요 성과

VCORE는 "자연어 → 검증 가능한 산업 시뮬레이션"이라는 AI Twin 비전을 **엔드투엔드로 작동**시켰다.
운영자는 채팅 한 줄로 시뮬레이션을 구동하고, 목표(병목률·처리량 등)를 주면 에이전트가 폐루프로
최적 구성을 탐색하며, 결과는 단순 수치가 아니라 **합격/불합격 판정**으로 돌아온다. 무거운 UE5
시뮬레이션과 가벼운 웹 관제를 픽셀 스트리밍으로 분리해, 어떤 단말에서도 트윈을 조종할 수 있게 했다.

그러나 이 프로젝트의 진짜 성과는 데모가 아니라 **엔지니어링 판단의 방어 가능성**이다.
- 운영 중이던 후처리 레이어가 최고 모델을 −21pp 악화시키고 있음을 **2,660회 벤치마크 + Wilson CI**로
  적발·수정(54.3 → 75.9%).
- "약한 모델이니 fine-tune"이라는 본능을, **프롬프트 2줄(KPI 22→94%)과 서빙 플래그 1개
  (disambiguation 63→91.7%)**라는 무료 레버로 무효화.
- 그 위에서 SFT는 목표를 재정의해 **프롬프트 증류(49→96%, 의존 −37pp 제거)**라는 별도 가치를 입증.
- 마지막으로 8GB VRAM 제약에 부딪혀 "단일 SFT로 전부"를 측정으로 기각(대화/보고 결함)한 뒤,
  **베이스 1개 + per-request LoRA 토글**(adapter_toggle)로 두 모델을 하나로 접어
  **라우팅 99.4% + 무결점 대화·보고**를 단일 엔드포인트에서 달성.

### 배운 점

1. **모델 성능 ≠ 시스템 성능.** 같은 후처리 로직이 모델 특성에 따라 정반대 결과를 낸다.
   둘을 분리해 평가하지 않으면 엉뚱한 곳을 고치게 된다.
2. **측정이 본능을 이긴다.** n=12로는 4개 프롬프트가 통계를 흔든다. argument-level 채점 + CI 분리
   기준이 일화를 발견으로 바꿨고, 불필요한 GPU-주 비용을 사전에 차단했다.
3. **가장 싼 레버부터.** fine-tuning(5~8일) 전에 프롬프트 2줄·서빙 플래그를 먼저 시험하는 것이
   훨씬 높은 ROI였다. 비싼 해법은 싼 해법이 실패한 뒤에.
4. **근본 원인은 보통 1~2단계 더 깊다.** "영상 DISCONNECTED"의 원인은 서버가 아니라 클라이언트
   재시도 정책이었고, "KPI 추출 실패"의 원인은 모델이 아니라 프롬프트의 누락이었다. 로그·증거를
   따라 한 단계 더 내려가는 습관이 결정적이었다.
5. **재현성은 데모의 신뢰도다.** 결정론적 process_model, 버전 관리되는 정적 케이스, 동일 런타임
   서빙(SFT/base) — 모든 비교를 apples-to-apples로 유지한 것이 모든 주장을 방어 가능하게 했다.
