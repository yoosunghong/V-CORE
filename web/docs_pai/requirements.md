# 요구사항 확정

본 문서는 스마트팜 디지털트윈 챗봇 데모의 1차 요구사항 기준선이다. 이후 구현 중 범위가 바뀌면 `PROPOSAL.md`, `ARCHITECTURE.md`, `PLAN.md`와 함께 갱신한다.

## 1. 데모 시연 범위

### 포함 범위

- Unreal Engine 5.7 프론트의 챗 UI에서 자연어 명령을 입력한다.
- 챗봇 백엔드는 세션을 만들고 사용자 메시지를 수신한다.
- 챗봇 백엔드는 스마트팜 상태 조회, LLM 도구 호출 판단, 로봇 명령 발행, 완료 보고 생성을 오케스트레이션한다.
- 데모 관제 서버는 bed, crop, greenhouse, sensor 기준 상태를 제공한다.
- 데모 IoT 플랫폼은 로봇 명령을 접수하고 `accepted`, `moving`, `working`, `completed`, `failed` 이벤트를 발행한다.
- Unreal 디지털트윈은 로봇 위치/작업 상태 이벤트를 수신해 화면 상태를 갱신할 수 있다.
- 대표 E2E 시나리오는 "2번 bed의 식물을 수확해줘"로 고정한다.

### 제외 범위

- 실제 로봇 하드웨어 제어
- 실제 생산 환경 관제 서버 연동
- 복수 사용자 권한/인증 체계
- Unreal 프로젝트 내부 UI 구현 전체
- 대규모 실시간 시계열 분석

## 2. Unreal Engine 5.7 프론트 연동 방식

초기 데모는 HTTP 요청 + WebSocket 이벤트 push 구조로 확정한다.

| 방향 | 방식 | 목적 |
| --- | --- | --- |
| Unreal -> Chatbot Backend | `POST /chat/messages` | 사용자 자연어 메시지 전송 |
| Unreal -> Chatbot Backend | `WS /chat/sessions/{session_id}/events` | 챗 응답, 진행 상태, 완료 보고 구독 |
| IoT Platform -> Unreal | `WS /digital-twin/events` | 로봇 이동, 작업, 센서/액추에이터 상태 이벤트 구독 |
| Unreal -> Chatbot Backend | `POST /chat/sessions` | 명시적 세션 생성이 필요한 경우 사용 |

원칙:

- Unreal은 LLM이나 로봇 제어 API를 직접 호출하지 않는다.
- Unreal의 챗 UI는 `session_id`를 기준으로 대화와 이벤트를 매칭한다.
- 모든 이벤트는 `correlation_id`를 포함해 사용자 요청부터 로봇 완료까지 추적 가능해야 한다.

## 3. 챗 UI 요청/응답 프로토콜

### 채팅 요청

```json
{
  "session_id": "session_demo_001",
  "message_id": "msg_user_001",
  "user_id": "demo_operator",
  "text": "2번 bed의 식물을 수확해줘",
  "locale": "ko-KR",
  "client": {
    "type": "unreal",
    "version": "5.7"
  },
  "sent_at": "2026-05-12T10:00:00+09:00"
}
```

### 채팅 응답

```json
{
  "session_id": "session_demo_001",
  "message_id": "msg_assistant_001",
  "correlation_id": "corr_demo_001",
  "status": "accepted",
  "text": "2번 bed의 수확 가능 여부를 확인하고 작업을 시작할게요.",
  "command_id": "cmd_harvest_002",
  "created_at": "2026-05-12T10:00:01+09:00"
}
```

### 진행 이벤트

```json
{
  "event_id": "evt_robot_moving_001",
  "event_type": "robot.moving",
  "correlation_id": "corr_demo_001",
  "session_id": "session_demo_001",
  "command_id": "cmd_harvest_002",
  "occurred_at": "2026-05-12T10:00:05+09:00",
  "payload": {
    "robot_id": "robot_harvester_01",
    "target": {
      "type": "bed",
      "id": "bed_002"
    },
    "progress": 0.35
  }
}
```

## 4. 로봇 제어 가능 명령 목록

초기 데모에서 허용되는 로봇 명령은 다음으로 제한한다.

| 명령 | 도구 이름 | 대상 | 설명 |
| --- | --- | --- | --- |
| 수확 | `harvest_bed` | `bed_id` | 지정 bed의 수확 작업을 수행한다. |
| 이동 | `move_to_bed` | `bed_id` | 로봇을 지정 bed 근처로 이동한다. |
| 상태 확인 | `inspect_bed` | `bed_id` | 작물/bed 상태를 확인한다. |
| 작업 취소 | `cancel_robot_command` | `command_id` | 아직 완료되지 않은 데모 명령을 취소한다. |

명령 발행 규칙:

- 모든 명령은 `command_id`, `correlation_id`, `idempotency_key`, `timeout_seconds`를 포함한다.
- `harvest_bed`는 관제 서버에서 해당 bed가 `harvest_ready=true`일 때만 발행한다.
- 명령은 데모 IoT 플랫폼으로만 발행하며, 실제 로봇 endpoint는 설정으로 분리한다.
- LLM 도구 호출 결과는 반드시 스키마 검증과 정책 검증을 통과해야 한다.

## 5. 스마트팜 도메인 객체

| 객체 | 필수 필드 | 설명 |
| --- | --- | --- |
| `greenhouse` | `greenhouse_id`, `name`, `zone_ids`, `status` | 데모 스마트팜 최상위 공간 |
| `bed` | `bed_id`, `zone_id`, `crop_id`, `position`, `status`, `harvest_ready` | 재배 bed와 수확 가능 상태 |
| `crop` | `crop_id`, `name`, `growth_stage`, `planted_at`, `expected_harvest_at` | 작물 품종과 생육 상태 |
| `robot` | `robot_id`, `type`, `status`, `position`, `battery_level` | 로봇 상태와 위치 |
| `sensor` | `sensor_id`, `type`, `zone_id`, `unit`, `status` | 환경 센서 메타데이터 |
| `actuator` | `actuator_id`, `type`, `zone_id`, `status`, `last_command_id` | 팬, 펌프, 조명 등 설비 |

초기 데모 기준 데이터:

- `greenhouse_demo_01`
- `bed_001`부터 `bed_004`
- `robot_harvester_01`
- 센서: 온도, 습도, CO2, 조도
- 액추에이터: 환기팬, 관수 펌프, LED 조명

## 6. 센서 데이터와 시계열 데이터 범위

초기 데모 데이터는 최근 24시간 범위의 5분 간격 샘플을 사용한다.

| 측정값 | 단위 | 범위 예시 | 저장소 |
| --- | --- | --- | --- |
| `temperature` | `celsius` | 18.0-30.0 | TimescaleDB |
| `humidity` | `percent` | 45.0-85.0 | TimescaleDB |
| `co2` | `ppm` | 350-1200 | TimescaleDB |
| `illuminance` | `lux` | 0-60000 | TimescaleDB |
| `robot_position` | `x,y,z` | Unreal 좌표계 매핑 값 | PostgreSQL 또는 TimescaleDB |
| `robot_task_status` | enum | `idle`, `moving`, `working`, `completed`, `failed` | PostgreSQL |

데모에서는 센서 데이터가 로봇 수확 가능 여부를 직접 결정하지 않는다. 수확 가능 여부는 관제 서버의 `bed.harvest_ready` 값을 기준으로 한다.

## 7. 담당자 인계를 위한 API 경계

| 담당 영역 | 제공 계약 | 주요 책임 |
| --- | --- | --- |
| Unreal 담당자 | `docs/api/unreal-events.md`, 챗/이벤트 payload | 챗 입력, 응답 표시, 디지털트윈 상태 반영 |
| 챗봇 백엔드 담당자 | `chatbot-backend.openapi.yaml` | 세션, 메시지, 오케스트레이션, 보고 생성 |
| 관제 서버 담당자 | `control-server.openapi.yaml` | bed/crop/greenhouse 상태 조회 |
| IoT 플랫폼 담당자 | `iot-platform.openapi.yaml` | 로봇 명령 접수, 상태 이벤트 발행 |
| 데이터 담당자 | seed schema와 샘플 데이터 | 도메인 기준 데이터, 시계열 샘플, RAG 문서 |

1차 구현에서 작성할 API 문서:

- `POST /chat/sessions`
- `POST /chat/messages`
- `GET /chat/sessions/{session_id}`
- `WS /chat/sessions/{session_id}/events`
- `GET /farm/beds/{bed_id}`
- `GET /farm/greenhouses/{greenhouse_id}/status`
- `POST /robots/commands`
- `GET /robots/commands/{command_id}`
- `POST /events/robot`
- `WS /digital-twin/events`

## 8. 미결정 항목

- Unreal이 IoT 이벤트를 직접 구독할지, 챗봇 백엔드가 중계할지의 최종 운영 구조
- TimescaleDB 단독 사용 여부와 InfluxDB 분리 여부
- Gemma 4 E2B 양자화 모델의 실제 도구 호출 포맷
- RAG 문서의 초기 범위와 담당자 제공 자료
