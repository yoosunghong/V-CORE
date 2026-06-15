# 피지컬AI 디지털트윈 XR콘텐츠 제작 시스템 설계서
## 챗봇 사이드 통합 API 명세서 v2.0 (실제 코드베이스 반영본)

**작성일**: 2026-05-22  
**대상 시스템**: Web F/E · Web B/E (FastAPI) · Unreal 디지털트윈 클라이언트  
**상태**: 실제 구현 반영 완료 (v1.6 Legacy 명세 개정판)

---

## 1. 공통 사항

### 1.1 Base URL
* **Web B/E (FastAPI)**: `http://localhost:8000/api` (또는 배포 환경의 백엔드 도메인 URL)
* ※ **DB Server 및 AI Agent URL 제거**: 기존 Legacy 명세에 존재하던 DB Server(`https://db.example.com/api`) 및 AI Agent GPU Farm(`https://agent.example.com`) 전용 외부 URL은 백엔드 프로세스 내부 모듈 통합(Clean Architecture 적용)으로 인해 제거되었습니다. 모든 외부 통신은 Web B/E가 단일 진입점(API Gateway) 역할을 수행합니다.

### 1.2 아키텍처 전제
| 원칙 | 설명 |
| :--- | :--- |
| **전 구간 통신 추적성** | 기존 JSON 바디 내의 복잡한 `header` 객체 대신, HTTP REST 통신 시 표준 HTTP Request Header인 `x-correlation-id`를 사용하여 메시지 추적(Traceability)을 보장합니다. |
| **프로토콜 하이브리드화** | 클라이언트에서 서버로의 사용자 메시지 송신은 REST API (`POST /chat/messages`)로 처리하여 멱등성 및 HTTP 표준 응답 코드를 보장합니다. 서버에서 클라이언트로의 비동기 제어 결과, 텍스트 스트리밍 등 실시간 갱신 사항은 WebSocket (`WS /chat/sessions/{session_id}/events`) 단방향 이벤트 스트림을 통해 실시간 푸시합니다. |
| **제어-피드백 비동기식 처리** | 로봇/하드웨어 제어 명령(Tool Calling) 발생 시, Web B/E는 즉시 수락(`accepted`) 상태의 응답을 반환(비차단형)합니다. 이후 실제 로봇의 동작 완료 및 갱신 상태는 IoT 플랫폼 등으로부터 백채널 API (`POST /events/robot-command`)로 수신되며, 가입된 WebSocket 이벤트를 통해 클라이언트(Unreal, Web F/E)로 실시간 브로드캐스팅됩니다. |

### 1.3 공통 헤더 구조
기존 명세서의 모든 JSON 데이터 최상위에 존재하던 `header` 객체 봉투(msg_id, timestamp, sender_id, receiver_id)는 모바일 및 웹 클라이언트 오버헤드 감소와 표준 REST 디자인 준수를 위해 **폐기**되었습니다.

#### 1) 메시지 추적용 HTTP 헤더
REST API 요청 시 아래 헤더를 선택적으로 전달하여 로그 추적에 사용합니다.
* `x-correlation-id`: (String, Optional) 요청-응답을 연계하여 추적하기 위한 고유 UUID. 누락 시 백엔드 내부에서 자동 생성합니다.

#### 2) 공통 에러 응답 구조 (HTTP 4xx / 5xx)
FastAPI 표준 규격과 일관성을 갖춘 공통 에러 형식입니다.
```json
{
  "detail": [
    {
      "loc": ["body", "message"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```
* 일반적인 비즈니스 로직 오류 또는 404 Not Found 에러인 경우 아래 구조로 반환됩니다.
```json
{
  "detail": "Unknown session: session_id_here"
}
```

---

## 2. Web F/E ↔ Web B/E 인터페이스

### 2.1 세션 생성 및 목록 조회

#### 2.1.1 세션 생성 [POST]
* **Endpoint**: `/chat/sessions`
* **설명**: 챗봇 UI 활성화 또는 디지털 트윈 접속 시 신규 대화 세션을 생성하고 ID를 발급합니다.
* **Request Body (CreateSessionRequest)**
```json
{
  "user_id": "user-001",
  "unreal_client_id": "ue-client-abc"
}
```
* **Response 201 Created (SessionResponse)**
```json
{
  "session_id": "session_a1b2c3d4",
  "user_id": "user-001",
  "unreal_client_id": "ue-client-abc",
  "created_at": "2026-05-22T07:00:00.000Z"
}
```

#### 2.1.2 세션 목록 조회 [GET] (신규 추가)
* **Endpoint**: `/chat/sessions`
* **설명**: 기존 생성된 대화 세션들의 목록을 요약 정보와 함께 역순 조회합니다.
* **Query Parameters**
  * `user_id` (String, Optional): 특정 사용자의 세션 필터링
  * `unreal_client_id` (String, Optional): 특정 Unreal 클라이언트의 세션 필터링
  * `limit` (Integer, Optional, Default: 20): 조회 건수 제한 (최대 50)
* **Response 200 OK (SessionListResponse)**
```json
{
  "sessions": [
    {
      "session_id": "session_a1b2c3d4",
      "user_id": "user-001",
      "unreal_client_id": "ue-client-abc",
      "created_at": "2026-05-22T07:00:00.000Z",
      "message_count": 12,
      "last_message_at": "2026-05-22T07:15:20.000Z",
      "last_message_preview": "Zone 1 수확 작업을 시작합니다…",
      "first_user_message_preview": "안녕, 오늘 수확 계획 알려줘"
    }
  ]
}
```

### 2.2 실시간 채널 및 채팅 인터페이스 (REST + WS)
기존 Legacy 명세의 양방향 WebSocket 채팅 프로토콜은 안정적인 HTTP 멱등키 지원과 오류 격리를 위해 REST와 WS의 하이브리드 결합 모델로 개선되었습니다.

#### 2.2.1 사용자 메시지 전송 [POST]
* **Endpoint**: `/chat/messages`
* **HTTP Header**: `x-correlation-id` (Optional)
* **설명**: 사용자의 자연어 명령을 전송하여 LLM 기반 추론 및 도구(로봇 제어) 실행 흐름을 시작합니다.
* **Request Body (ChatRequest)**
```json
{
  "session_id": "session_a1b2c3d4",
  "message": "Zone 1 수확 로봇 가동해 줘.",
  "user_id": "user-001",
  "unreal_client_id": "ue-client-abc",
  "idempotency_key": "idem-key-9999"
}
```
* ※ `session_id`를 누락하거나 `null`로 보낼 경우, 시스템은 자동으로 새로운 대화 세션을 생성하여 대화를 시작합니다.
* **Response 200 OK (ChatResponse)**
```json
{
  "session_id": "session_a1b2c3d4",
  "correlation_id": "evt_uuid_123456",
  "message": {
    "message_id": "msg_987654",
    "session_id": "session_a1b2c3d4",
    "role": "assistant",
    "content": "Zone 1의 작물 수확 명령을 분석 중입니다...",
    "correlation_id": "evt_uuid_123456",
    "created_at": "2026-05-22T07:15:21.000Z"
  },
  "command_id": "cmd_550e8400",
  "status": "accepted",
  "events": [
    {
      "event_id": "evt_001",
      "event_type": "text_stream",
      "correlation_id": "evt_uuid_123456",
      "session_id": "session_a1b2c3d4",
      "command_id": "cmd_550e8400",
      "occurred_at": "2026-05-22T07:15:21.000Z",
      "payload": {
        "delta": "Zone 1의 작물 수확 명령을 분석 중입니다..."
      }
    }
  ]
}
```

#### 2.2.2 WebSocket 단방향 이벤트 스트리밍 수신 [WS]
* **Endpoint**: `/chat/sessions/{session_id}/events`
* **설명**: 특정 세션에 대한 비동기 로봇 제어 과정, 중간 추론 텍스트 토큰 스트리밍, 기기 완료 보고 등의 이벤트를 수신하기 위한 전용 단방향 WebSocket 채널입니다.
* **동작 원리**:
  1. 연결 성립(Handshake) 즉시, 세션에 할당된 과거 이벤트 이력을 클라이언트에 먼저 재생(Replay)합니다.
  2. 이후 발생하는 신규 도메인 이벤트(`DomainEvent`)를 실시간으로 구독하여 `JSON` 구조로 클라이언트에 푸시합니다.
* **WebSocket 이벤트 구조 (DomainEvent)**
```json
{
  "event_id": "evt_002",
  "event_type": "robot_command_triggered",
  "correlation_id": "evt_uuid_123456",
  "session_id": "session_a1b2c3d4",
  "command_id": "cmd_550e8400",
  "occurred_at": "2026-05-22T07:15:25.000Z",
  "payload": {
    "command_name": "harvest_bed",
    "parameters": {
      "bed_id": 1,
      "robot_id": "AMR_1"
    }
  }
}
```

##### 주요 `event_type` 명세:
* `text_stream`: AI의 실시간 응답 텍스트 조각(delta) 전송.
* `robot_command_triggered`: LangGraph 에이전트가 로봇 동작(Tool)을 결정하여 명령을 IoT 플랫폼에 발행했음을 알림.
* `robot_command_completed`: 물리 로봇이 동작을 성공적으로 마치고 B/E에 콜백(Event)을 보고했음을 전파.
* `robot_command_failed`: 로봇 실행 오류, 장애 또는 시간 초과가 발생했음을 전파.

---

### 2.3 대화 이력 조회 [GET]

* **Endpoint**: `/chat/sessions/{session_id}/messages`
* **설명**: 특정 세션의 모든 과거 대화 메시지 목록을 조회합니다.
* **Query Parameters**
  * `limit` (Integer, Optional): 가져올 메시지의 개수 제한. (B/E 설정 기본값 사용)
  * `max_content_chars` (Integer, Optional): 반환 텍스트의 문자열 절단 크기 제한 (메시지 길이 최소화 최적화용).
* **Response 200 OK (SessionMessagesResponse)**
```json
{
  "session_id": "session_a1b2c3d4",
  "messages": [
    {
      "message_id": "msg_0001",
      "session_id": "session_a1b2c3d4",
      "role": "user",
      "content": "Zone 1 수확 로봇 가동해 줘.",
      "correlation_id": "evt_uuid_123456",
      "created_at": "2026-05-22T07:15:00.000Z"
    },
    {
      "message_id": "msg_0002",
      "session_id": "session_a1b2c3d4",
      "role": "assistant",
      "content": "Zone 1 수확 로봇(AMR_1)에 수확 제어 명령을 하달하였습니다. 작업 진행률은 실시간 모니터링을 확인하십시오.",
      "correlation_id": "evt_uuid_123456",
      "created_at": "2026-05-22T07:15:05.000Z"
    }
  ]
}
```

---

### 2.4 대시보드 오버레이 정보 조회 [GET] (신규 추가)

* **Endpoint**: `/dashboard/overlay`
* **설명**: 스마트팜 온실 전체의 상태 지표(안정성, 급수 효율, CO2 농도 등), 구역 활성화 상태, 활성 워크로드 백분율 및 실시간 커맨드 피드(로그) 리스트를 모아 한 번에 반환합니다. 챗봇 UI 상단이나 백그라운드 위젯 데이터 렌더링에 적합합니다.
* **Response 200 OK (OverlayDashboardResponse)**
```json
{
  "greenhouse_id": "GH-ZONE-048-ALPHA",
  "zones": [
    { "id": "zone-1", "name": "ZONE 1", "subtitle": "Smart control - cultivation", "active": false },
    { "id": "zone-2", "name": "ZONE 2", "subtitle": "Smart control - packaging", "active": true },
    { "id": "zone-3", "name": "ZONE 3", "subtitle": "Smart control - logistics", "active": false }
  ],
  "metrics": [
    {
      "id": "zone-stability",
      "title": "Zone Stability",
      "subtitle": "구역 안정성",
      "value": 100.0,
      "unit": "%",
      "trend_percent": 2.1,
      "series": [8, 9, 10, 24, 31, 36, 45, 52]
    }
  ],
  "workloads": [
    { "id": "harvesting", "title": "Harvesting", "subtitle": "Harvest", "value": 0.0, "unit": "%", "status": "READY", "active": true }
  ],
  "command_feed": [
    "구역 D-01, 밸브 보정 작업 항목을 불러 들이고 있습니다.",
    "구역 D-01, 밸브 보정 요청 작업을 서버에 요청 중입니다."
  ],
  "generated_at": "2026-05-22T07:20:00.000Z"
}
```

---

### 2.5 Unreal 구역 포커싱 요청 [POST] (신규 추가)

* **Endpoint**: `/unreal/zones/{zone_id}/focus`
* **설명**: 웹 챗봇 클라이언트나 제어 프로그램에서 언리얼 엔진 5.7 디지털 트윈 상의 특정 Zone(구역 1~3) 카메라 및 정보를 포커싱하도록 트리거 명령을 보냅니다.
* **Path Parameters**
  * `zone_id` (String, Required): 포커싱 대상 구역 명칭 (`zone-1` \| `zone-2` \| `zone-3`)
* **Request Body (UnrealZoneFocusRequest)**
```json
{
  "unreal_client_id": "ue-webview",
  "idempotency_key": "focus-idem-key-888"
}
```
* **Response 202 Accepted (UnrealZoneFocusResponse)**
```json
{
  "status": "accepted",
  "zone_id": "zone-1",
  "unreal_client_id": "ue-webview",
  "command_id": "uecmd_994b2a1a8c08",
  "api_path": "/digital-twin/zones/zone-1/focus",
  "issued_at": "2026-05-22T07:22:00.000Z"
}
```

---

### 2.6 로봇 제어 완료 이벤트 수신 [POST] (신규 추가)

* **Endpoint**: `/events/robot-command`
* **설명**: 백채널 수신용 API로, IoT 플랫폼, 로봇 제어기 또는 외부 시뮬레이터가 특정 로봇 명령(`command_id`)의 비동기 실행 완료(성공/실패) 상태를 Web B/E에 보고할 때 사용합니다. Web B/E는 이 호출을 수신하여 세션에 이벤트를 발행하고 WebSocket 클라이언트에 진행 완료를 보고합니다.
* **Request Body (CompletionEventRequest)**
```json
{
  "event_type": "robot_command_completed",
  "correlation_id": "evt_uuid_123456",
  "session_id": "session_a1b2c3d4",
  "command_id": "cmd_550e8400",
  "payload": {
    "result": "success",
    "harvested_count": 35,
    "duration_seconds": 120
  }
}
```
* **Response 200 OK (ChatResponse)**
```json
{
  "session_id": "session_a1b2c3d4",
  "correlation_id": "evt_uuid_123456",
  "message": {
    "message_id": "msg_completed_999",
    "session_id": "session_a1b2c3d4",
    "role": "assistant",
    "content": "구역 1의 수확 로봇 명령이 성공적으로 완료되었습니다. 수확 수량: 35개.",
    "correlation_id": "evt_uuid_123456",
    "created_at": "2026-05-22T07:24:00.000Z"
  },
  "command_id": "cmd_550e8400",
  "status": null,
  "events": [
    {
      "event_id": "evt_completed_callback",
      "event_type": "robot_command_completed",
      "correlation_id": "evt_uuid_123456",
      "session_id": "session_a1b2c3d4",
      "command_id": "cmd_550e8400",
      "occurred_at": "2026-05-22T07:24:00.000Z",
      "payload": {
        "result": "success",
        "harvested_count": 35,
        "duration_seconds": 120
      }
    }
  ]
}
```

---

## 3. Web B/E ↔ AI Agent 내부 인터페이스 (추상화됨)

기존 명세서의 `POST /ai-agent/inference/chat` HTTP 통신 채널은 Web B/E의 LangGraph 오케스트레이터 및 하위 에이전트 결합체(`app/application/multi_response_graph.py`) 내부 프로세스 호출로 완전히 대체되었습니다.

### 3.1 내부 오케스트레이션 및 상태 전이
* **동작 정의**: Web B/E가 REST API 또는 이벤트 트리거를 감지하면 내부 `ChatOrchestrator` 클래스가 인스턴스화된 LangGraph 상태 그래프(StateGraph)를 비동기 실행(`graph.astream()`)합니다.
* **내부 흐름**:
  1. **User Message Input**: 사용자의 입력을 받아 대화 맥락 및 히스토리를 로드합니다.
  2. **Agent LLM Inference Node**: LLM이 사용자의 발화를 판단하여 일반 응답(Text Response) 혹은 도구 호출(Tool Calling) 여부를 결정합니다.
  3. **Conditional Router**: 도구 호출이 필요하면 로봇 액션 노드로 분기하고, 그렇지 않으면 최종 응답을 빌드하여 클라이언트 이벤트 큐로 내보냅니다.

---

## 4. AI Agent (Control) ↔ Web B/E 내부 인터페이스 (추상화됨)

기존 명세서의 `POST /ai-agent/control/execute` 통신 채널은 의존성 결합을 막고 보안을 극대화하기 위하여, 백엔드 내부의 **도구 계약(Tool Contract) 인터페이스** 및 **IoT 클라이언트 어댑터**를 통한 메시징(MQTT/gRPC 등) 구조로 추상화되었습니다.

### 4.1 비동기 제어 명령 발행 인터페이스
* **동작 정의**: 에이전트 내의 Tool 실행기(`app/tools/robot.py`)가 실행을 호출하면, Web B/E의 `ControlServerClient` 인터페이스 어댑터를 경유하여 디지털 트윈 서버 및 스마트팜 기기 제어 플랫폼에 통신(Publish)을 발생시킵니다.
* **제어 멱등성 및 상태**:
  * 모든 제어 요청은 고유한 `command_id` 및 `idempotency_key`를 포함하여 발급됩니다.
  * 제어 도구 호출 결과는 일단 `CommandStatus.ACCEPTED`로 마킹되어 F/E에 반환되며, 로봇이 최종 작업을 수행한 결과는 비동기 백채널(`2.6 로봇 제어 완료 이벤트 수신`)을 거쳐 동기화됩니다.

---

## 5. AI Agent (Data) ↔ DB Server 내부 인터페이스 (추상화됨)

기존 명세서의 `GET /ai-agent/data/sensor`, `GET /zone-summary/{zone_id}` HTTP 통신 채널은 백엔드 내부의 **Repository 데이터 액세스 레이어**로 래핑되어 추상화되었습니다.

### 5.1 시계열 및 데이터 원격 조회 기법
* **동작 정의**: 에이전트 내의 온실 상태 조회 도구(RAG 또는 DB 쿼리 도구)가 실행될 때, REST API 통신 비용 없이 DB Connection Pool을 활용하여 TimescaleDB 및 PostgreSQL 데이터베이스에 다이렉트 쿼리를 수행합니다.
* **인터페이스 구현**:
  * `IotTelemetryClient`: 실시간 온실 환경 센서 데이터 조회 담당
  * `FarmRepository`: 구역(Zone)별 작물 현황, 침입 탐지 횟수, 로봇 접근성 및 요약 데이터 조회 담당

---

## 6. Web B/E ↔ DB Server 내부 인터페이스 (추상화됨)

기존 명세서의 `POST /data/chat-logs`는 Web B/E 프로세스 내부의 데이터 영속성 계층인 `SessionRepository` 및 `MessageRepository`로 통합되었습니다.

### 6.1 세션 및 메시지 영구 저장
* **동작 정의**: 대화 세션의 활성화, 신규 메시지 수신 및 발생한 도메인 이벤트들은 사용자 응답이 완료되는 시점 혹은 비동기 저장 백그라운드 태스크에서 로컬 데이터베이스 또는 메모리 DB 인스턴스에 즉각 기록됩니다.
* **영속 모델**: `ChatSession`, `ChatMessage`, `DomainEvent` 등 Pydantic 기반의 정교한 데이터 도메인 모델 구조를 데이터베이스 스키마와 1:1 매핑하여 관계형 저장소에 영구 적재합니다.

---

## 7. API 목록 요약

현재 FastAPI 백엔드(`http.py`, `websocket.py`)에 바인딩되어 동작하는 인터페이스 목록입니다.

| 순번 | 프로토콜 | Method | Endpoint | 데이터 모델 | 목적 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **2.1.1** | HTTP | `POST` | `/chat/sessions` | `CreateSessionRequest` $\rightarrow$ `SessionResponse` | 신규 대화 세션 활성화 및 ID 발급 |
| **2.1.2** | HTTP | `GET` | `/chat/sessions` | None $\rightarrow$ `SessionListResponse` | 전체 세션 요약 리스트 조회 |
| **2.2.1** | HTTP | `POST` | `/chat/messages` | `ChatRequest` $\rightarrow$ `ChatResponse` | 자연어 입력 전송 (챗 대화 시작) |
| **2.2.2** | WS | `WS` | `/chat/sessions/{session_id}/events` | `DomainEvent` (Outbound 스트리밍) | 대화/제어 실시간 비동기 이벤트 스트림 |
| **2.3** | HTTP | `GET` | `/chat/sessions/{session_id}/messages` | None $\rightarrow$ `SessionMessagesResponse` | 특정 세션의 대화 내역 전체 조회 |
| **2.4** | HTTP | `GET` | `/dashboard/overlay` | None $\rightarrow$ `OverlayDashboardResponse` | 스마트팜 종합 지표 및 로그 피드 조회 |
| **2.5** | HTTP | `POST` | `/unreal/zones/{zone_id}/focus` | `UnrealZoneFocusRequest` $\rightarrow$ `UnrealZoneFocusResponse` | 디지털 트윈 언리얼 엔진 특정 구역 포커싱 |
| **2.6** | HTTP | `POST` | `/events/robot-command` | `CompletionEventRequest` $\rightarrow$ `ChatResponse` | 로봇/기기 물리 동작 완료 보고 이벤트 수신 |
| **System**| HTTP | `GET` | `/health` | None $\rightarrow$ String | 백엔드 헬스 체크용 |

---

## 8. 참고 및 미결 사항 (TBD)

### 8.1 멱등성 키 (`idempotency_key`) 관리 정책
* **목적**: 클라이언트 네트워크 장애 등으로 인한 로봇 중복 제어 및 대화 세션 폭주 방지.
* **현황**: `POST /chat/messages` 및 `POST /unreal/zones/{zone_id}/focus` 요청 본문에 고유한 키값을 인계 가능하며, 백엔드 메모리 캐시 및 DB를 통해 동일 키에 대한 처리가 중복 실행되지 않도록 가드하고 있습니다.

### 8.2 WebSocket 생명주기 관리 및 연결 끊김 정책
* **목적**: 모바일 뷰 비활성화, 언리얼 엔진 에디터 종료 시 백엔드 소켓 포트 누수 방지.
* **현황**: 클라이언트 단에서 `close` 신호를 수신하거나 비정상 연결 종료 시, 백엔드 내부의 이벤트 버스 구독 해제(`unsubscribe`)가 정상 동작하도록 구현되어 있습니다. 향후 핑-퐁 타임아웃 주기를 30초 내외로 튜닝하여 네트워크 불안정 시의 자동 재연결(Reconnect) 정책 확정이 필요합니다.
