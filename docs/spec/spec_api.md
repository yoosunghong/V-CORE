> **DEPRECATED (2026-06-04):** The backend↔UE5 contract changed with the Virtual Process
> migration. See [spec_virtual_process.md](spec_virtual_process.md) for the current
> endpoints (`/agv/command`, `/sim/pause|resume|speed`, `/sim/status`, `/internal/ue5/events`).
> The design below is kept for history only.

> **CURRENT ADDENDUM (2026-06-05):** The active browser-facing simulation API has been
> restored on top of the Virtual Process backend. The canonical details live in
> [spec_virtual_process.md](spec_virtual_process.md), section "Scenario and playback API".
> The active routes are:
> - `GET|POST /api/v1/scenarios`
> - `PUT|DELETE /api/v1/scenarios/{scenario_id}`
> - `POST /api/v1/scenarios/{scenario_id}/duplicate`
> - `POST /api/v1/scenarios/{scenario_id}/run`
> - `GET /api/v1/scenarios/{scenario_id}/runs`
> - `POST /api/v1/runs/{run_id}/pause|resume|stop|speed`
> - `GET /api/v1/runs/{run_id}/result`
>
> The backend stores scenarios/runs and proxies live control to UE5
> `/sim/start|pause|resume|stop|speed`. UE5 completion events with `payload.run_id`
> and `payload.kpis` update the saved run result.

# API Exchange Specification — UE5 ↔ Web Backend

**Project:** VCORE — AI Twin Platform  
**Version:** 0.1 (Demo Prototype)

---

## 1. Communication Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  Browser (React)                                                    │
│  GET/POST /api/v1/*   ←───────────────────────────────────────────  │
│  WS /ws/dashboard/{run_id}  ←──────────────────────────────────── │
└────────────────────────┬────────────────────────────────────────────┘
                         │  HTTP + WebSocket
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Web Backend (FastAPI)                                              │
│  POST /api/v1/simulation/start  ──────────────────────────────────> │  HTTP
│  WS  /ws/ue5/stream/{run_id}    <──────────────────────────────── │  WS stream
│  POST /internal/ue5/simulation/{run_id}/complete  <────────────── │  HTTP
└────────────────────────────────────────────────────────────────────-┘
                         │  HTTP (local)
                         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  UE5 Simulation (localhost:7777)                                    │
│  POST /sim/start  <────────────────────────────────────────────── │
└─────────────────────────────────────────────────────────────────────┘
```

**Direction legend:**
- `Web → UE5`: HTTP commands (start/stop simulation)
- `UE5 → Web`: WebSocket stream (real-time events) + HTTP POST (final report)
- `Browser → Web`: Standard REST + WebSocket (dashboard feed)

---

## 2. Authentication

### 2.1 UE5 ↔ Web (Internal)

All requests between UE5 and the web backend use a pre-shared API key:

```
Header: X-AGV-API-Key: <api_key>
```

- Configured in UE5: `Config/DefaultGame.ini` `[AGVSim] APIKey=`
- Configured in backend: `.env` `AGV_API_KEY=`
- Backend validates key in `app/core/security.py` as a FastAPI dependency.
- If key is missing or wrong → `401 Unauthorized`.

### 2.2 Browser ↔ Web (Public API)

Demo: No authentication on public API routes. (Add JWT for production.)

---

## 3. REST Endpoints

### 3.1 Web → UE5: Start Simulation

**Web backend calls UE5 local HTTP server when user triggers a simulation.**

```
POST http://localhost:7777/sim/start
Content-Type: application/json
X-AGV-API-Key: <key>
```

**Request Body:**
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "speed": 60.0,
  "duration": 3600,
  "policy_id": "POLICY_FIFO",
  "agv_count": 3,
  "bottleneck_threshold_sec": 10.0,
  "acceptance": [
    { "label": "throughput >= 70/h", "metric": "throughput",      "comparator": ">=", "threshold": 70 },
    { "label": "wait < 12s",         "metric": "avg_wait_sec",     "comparator": "<=", "threshold": 12 },
    { "label": "no collisions",      "metric": "collision_count",  "comparator": "==", "threshold": 0 }
  ]
}
```

> Note: when the agent drives the run, these fields are nested under a `parameters` object (the agent
> command envelope); the engine reads either a flat body or `parameters`. `acceptance` is read from the
> same object as the sim params.

| Field | Type | Required | Description |
|---|---|---|---|
| `run_id` | `string (UUID)` | Yes | Backend-assigned run identifier |
| `speed` | `float` | Yes | Sim speed multiplier (1.0 = real-time, 60.0 = 1 min/sec) |
| `duration` | `int` | Yes | Simulated duration in seconds |
| `policy_id` | `string` | Yes | One of: `POLICY_FIFO`, `POLICY_PRIORITY_LOADED`, `POLICY_ROUND_ROBIN` |
| `agv_count` | `int` | No | Number of AGVs to activate (default: 3) |
| `bottleneck_threshold_sec` | `float` | No | Bottleneck warning threshold in simulated seconds (default: 10.0) |
| `acceptance` | `array` | No | **F4** scenario acceptance criteria; engine returns a PASS/FAIL `verdict` at completion |
| `acceptance[].metric` | `string` | Yes (per item) | One of: `throughput`, `avg_wait_sec`, `collision_count`, `uptime_ratio`, `active_agvs` |
| `acceptance[].comparator` | `string` | Yes (per item) | One of: `>=`, `<=`, `==` |
| `acceptance[].threshold` | `float` | Yes (per item) | Value the metric is compared against |
| `acceptance[].label` | `string` | No | Human-readable criterion echoed back in the verdict (auto-filled if omitted) |

**Response:**
```json
{ "status": "started", "run_id": "550e8400-e29b-41d4-a716-446655440000" }
```

**Error Response:**
```json
{ "error": "ALREADY_RUNNING", "message": "A simulation is already in progress." }
```

---

### 3.2 Web → UE5: Stop Simulation

```
POST http://localhost:7777/sim/stop
Content-Type: application/json
X-AGV-API-Key: <key>
```

**Request Body:**
```json
{ "run_id": "550e8400-e29b-41d4-a716-446655440000" }
```

**Response:**
```json
{ "status": "stopped", "run_id": "550e8400-e29b-41d4-a716-446655440000" }
```

For the demo prototype, UE5 may return this response before real AGV gameplay logic exists. The purpose is to release the backend lock cleanly and allow the next run to start.

---

### 3.3 UE5 → Web: Submit Final Report

**UE5 calls this when the simulation ends (timer expires, stopped, or all AGVs halted).**

```
POST http://[backend_host]:8000/internal/ue5/simulation/{run_id}/complete
Content-Type: application/json
X-AGV-API-Key: <key>
```

**Request Body:**
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "stop_reason": "TIMER_EXPIRED",
  "sim_duration_actual": 3600.0,
  "kpis": {
    "throughput": 12.4,
    "avg_wait_time": 8.3,
    "collision_risk": 0.5,
    "uptime": 0.87
  },
  "verdict": {
    "passed": false,
    "checks_total": 3,
    "passed_labels": ["throughput >= 70/h", "wait < 12s"],
    "failed_labels": ["no collisions"]
  },
  "timeline": [
    {
      "sim_timestamp": 0.0,
      "event_type": "AGV_STATE_CHANGE",
      "agv_id": "AGV-1",
      "data": { "from_state": "IDLE", "to_state": "MOVING_TO_PICKUP" }
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `run_id` | `string` | Must match the run_id from Start_Sim |
| `stop_reason` | `string` | `TIMER_EXPIRED` \| `STOP_COMMAND` \| `ALL_STOPPED` |
| `sim_duration_actual` | `float` | Actual simulated seconds elapsed |
| `kpis.throughput` | `float` | Tasks completed per simulated hour |
| `kpis.avg_wait_time` | `float` | Mean section wait time in simulated seconds |
| `kpis.collision_risk` | `float` | Collisions per simulated hour |
| `kpis.uptime` | `float` | Active task fraction (0.0–1.0), averaged over all AGVs |
| `verdict` | `object` | **F4** scenario verdict; present only when the run carried `acceptance` criteria |
| `verdict.passed` | `bool` | Overall result — `true` only if every criterion passed |
| `verdict.checks_total` | `int` | Number of criteria evaluated |
| `verdict.passed_labels` | `array` | Labels of criteria that passed |
| `verdict.failed_labels` | `array` | Labels of criteria that failed |
| `timeline` | `array` | Complete ordered list of all SimEvents during the run |

> In the Virtual Process stack the verdict travels on the chat-correlated `robot.command.completed`
> event payload (alongside `kpis`); the report agent surfaces the PASS/FAIL in chat. See
> [spec_virtual_process.md](spec_virtual_process.md).

**Response:**
```json
{ "status": "received", "report_id": "abc12345-..." }
```

---

## 4. WebSocket: Real-Time Event Stream

### 4.1 UE5 → Web (Inbound Stream)

**UE5 connects to this endpoint immediately after receiving Start_Sim:**

```
ws://[backend_host]:8000/ws/ue5/stream/{run_id}
Headers: X-AGV-API-Key: <key>
```

UE5 sends one JSON message per event, newline-delimited:

#### SimEvent Message Schema

```json
{
  "type": "SimEvent",
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "sim_timestamp": 42.75,
  "event_type": "AGV_STATE_CHANGE",
  "agv_id": "AGV-2",
  "data": {}
}
```

| Field | Type | Description |
|---|---|---|
| `type` | `"SimEvent"` | Fixed discriminator string |
| `run_id` | `string` | Must match the started run |
| `sim_timestamp` | `float` | Simulated seconds from run start |
| `event_type` | `string` | See event types below |
| `agv_id` | `string \| null` | AGV identifier (null for non-AGV events) |
| `data` | `object` | Event-specific payload |

#### Event Types and Data Payloads

**`AGV_STATE_CHANGE`**
```json
{
  "from_state": "MOVING_TO_PICKUP",
  "to_state": "LOADING",
  "position": { "x": 120.5, "y": 340.0, "z": 0.0 },
  "speed": 0.0,
  "battery": 85.2
}
```

**`TASK_COMPLETE`**
```json
{
  "task_id": "T-042",
  "task_type": "DELIVERY",
  "duration_sec": 47.3,
  "agv_id": "AGV-1"
}
```

**`COLLISION`**
```json
{
  "agv_id_a": "AGV-1",
  "agv_id_b": "AGV-2",
  "position": { "x": 200.0, "y": 200.0, "z": 0.0 },
  "relative_velocity": 3.2
}
```
> Note: `agv_id` at top level is `null` for COLLISION (both AGVs listed in `data`).

**`BOTTLENECK`**
```json
{
  "section_id": "INTERSECTION_X",
  "wait_duration_sec": 12.4,
  "queued_agv_ids": ["AGV-2", "AGV-3"]
}
```

**`SIM_PROGRESS`** (sent every 5 simulated seconds)
```json
{
  "elapsed_sim_sec": 300.0,
  "total_sim_sec": 3600.0,
  "tasks_completed": 6,
  "active_agv_count": 3
}
```

#### Heartbeat

UE5 sends a heartbeat every 5 real seconds to keep the connection alive:
```json
{ "type": "Heartbeat", "run_id": "...", "sim_timestamp": 300.0 }
```

---

### 4.2 Web → Browser (Dashboard Stream)

**Browser subscribes to relay stream for a running simulation:**

```
ws://[backend_host]:8000/ws/dashboard/{run_id}
```

The backend relays the exact same `SimEvent` JSON objects from UE5 to the browser.
Additional envelope message types sent by the backend:

**`RunStatus`** (sent on connect and on status change)
```json
{
  "type": "RunStatus",
  "run_id": "...",
  "status": "running",
  "started_at": "2026-04-20T10:30:00Z"
}
```

**`RunComplete`** (sent when UE5 posts final report)
```json
{
  "type": "RunComplete",
  "run_id": "...",
  "stop_reason": "TIMER_EXPIRED",
  "kpis": {
    "throughput": 12.4,
    "avg_wait_time": 8.3,
    "collision_risk": 0.5,
    "uptime": 0.87
  }
}
```

---

## 5. REST: Public API (Browser ↔ Backend)

### 5.1 Start Simulation (from Browser/Agent)

```
POST /api/v1/simulation/start
Content-Type: application/json
```

**Request:**
```json
{
  "scenario_id": "uuid-or-null",
  "name": "Test — Add 1 AGV",
  "parameters": {
    "speed": 60.0,
    "duration": 3600,
    "policy_id": "POLICY_FIFO",
    "agv_count": 3,
    "bottleneck_threshold_sec": 10.0
  }
}
```

**Response `202 Accepted`:**
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "created_at": "2026-04-20T10:30:00Z"
}
```

**Error `409 Conflict`:**
```json
{ "error": "SIMULATION_ALREADY_RUNNING", "message": "..." }
```

Before returning `409`, the backend first checks whether the existing `running` row is stale. If it is older than the demo stale-run timeout, the backend marks it as `error` and accepts the new run instead.

If the backend accepts the run but cannot successfully hand off `POST /sim/start` to UE5, the run remains `pending` and the backend logs the UE5 handoff failure with status code / response body when available.

---

### 5.2 Get Run Status

### 5.2.0 List Runs

```
GET /api/v1/simulation/
GET /api/v1/simulation/runs
```

Both routes return the same newest-first run history used by the dashboard and comparison selectors.

**Response `200`:**
```json
[
  {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "scenario_id": "650e8400-e29b-41d4-a716-446655440000",
    "scenario_name": "기본 운영 (AGV 3대, 기본 속도)",
    "status": "completed",
    "started_at": "2026-04-23T09:00:00+00:00",
    "ended_at": "2026-04-23T10:00:00+00:00",
    "created_at": "2026-04-23T09:00:00+00:00"
  }
]
```

Run-specific endpoints return `400 INVALID_RUN_ID` when `{run_id}` is not a UUID.

---

### 5.2.1 Get Run Status

```
GET /api/v1/simulation/{run_id}
```

**Response `200`:**
```json
{
  "run_id": "...",
  "status": "completed",
  "scenario_name": "Test — Add 1 AGV",
  "parameters": { ... },
  "started_at": "2026-04-20T10:30:00Z",
  "ended_at": "2026-04-20T10:31:00Z",
  "kpis": {
    "throughput": 12.4,
    "avg_wait_time": 8.3,
    "collision_risk": 0.5,
    "uptime": 0.87
  }
}
```

### 5.2.2 Stop Active Run

```
POST /api/v1/simulation/{run_id}/stop
Content-Type: application/json
```

**Response `200`:**
```json
{
  "run_id": "...",
  "status": "stopped"
}
```

The backend updates the run row immediately for demo recovery and then sends a best-effort stop request to UE5.

---

### 5.3 Agent Chat

```
POST /api/v1/agent/chat
Content-Type: application/json
Accept: text/event-stream
```

**Request:**
```json
{
  "session_id": "session-uuid",
  "message": "I want to increase throughput by 10%. What if I add one more AGV?"
}
```

**Response: SSE Stream**
```
data: {"type":"token","content":"Based on current KPIs, "}
data: {"type":"token","content":"throughput is 12.4 tasks/hour. "}
data: {"type":"tool_call","tool":"get_current_kpis","input":{"run_id":"latest"}}
data: {"type":"tool_result","tool":"get_current_kpis","output":{"throughput":12.4,...}}
data: {"type":"token","content":"Adding an AGV would likely cause a bottleneck..."}
data: {"type":"action","action":"propose_scenario","scenario_id":"new-uuid","params":{...}}
data: {"type":"done"}
```

---

### 5.4 KPI Comparison

```
GET /api/v1/reports/compare?baseline={run_id}&modified={run_id}
```

**Response `200`:**
```json
{
  "baseline": {
    "run_id": "...",
    "scenario_name": "Baseline",
    "kpis": { "throughput": 11.2, "avg_wait_time": 9.1, "collision_risk": 0.8, "uptime": 0.82 }
  },
  "modified": {
    "run_id": "...",
    "scenario_name": "Add 1 AGV",
    "kpis": { "throughput": 12.4, "avg_wait_time": 10.2, "collision_risk": 0.5, "uptime": 0.87 }
  },
  "delta": {
    "throughput": { "absolute": 1.2, "percent": 10.7 },
    "avg_wait_time": { "absolute": 1.1, "percent": 12.1 },
    "collision_risk": { "absolute": -0.3, "percent": -37.5 },
    "uptime": { "absolute": 0.05, "percent": 6.1 }
  }
}
```

### 5.4.1 AI Analysis Report

```
POST /api/v1/reports/{report_id}/analyze
Content-Type: application/json
```

The backend sends the KPI comparison to Gemini and stores the returned JSON in `reports.llm_analysis`.
All user-facing text values in the returned JSON must be Korean, including `summary`, `improvements`,
`concerns`, and `recommendation`.

**Response `200`:**
```json
{
  "summary": "변경 실행은 처리량을 개선했지만 평균 대기 시간이 증가했습니다.",
  "improvements": ["처리량이 10.7% 증가했습니다."],
  "concerns": ["평균 대기 시간이 12.1% 증가했습니다."],
  "recommendation": "처리량 개선 효과는 유지하되 교차로 대기 완화 정책을 추가 검증하세요."
}
```

---

### 5.5 Decision Submission

```
POST /api/v1/reports/{report_id}/decision
Content-Type: application/json
```

**Request:**
```json
{
  "decision": "approved",
  "notes": "Throughput improvement outweighs the marginal wait time increase.",
  "decided_by": "Manager Kim"
}
```

**Response `200`:**
```json
{
  "report_id": "...",
  "status": "approved",
  "decided_by": "Manager Kim",
  "approved_at": "2026-04-20T11:00:00Z"
}
```

---

## 6. Error Code Reference

| HTTP Status | Error Code | Meaning |
|---|---|---|
| 400 | `INVALID_PARAMETERS` | Request body validation failed |
| 401 | `UNAUTHORIZED` | Missing or invalid API key |
| 404 | `NOT_FOUND` | Resource does not exist |
| 409 | `SIMULATION_ALREADY_RUNNING` | UE5 is busy with another run |
| 422 | `VALIDATION_ERROR` | Pydantic schema mismatch |
| 500 | `INTERNAL_ERROR` | Unexpected server error |
| 503 | `UE5_UNAVAILABLE` | Cannot reach UE5 HTTP server |

All error responses follow:
```json
{ "error": "ERROR_CODE", "message": "Human-readable description." }
```

---

## 7. Data Type Conventions

| Convention | Rule |
|---|---|
| IDs | UUID v4 strings |
| Timestamps | ISO 8601 UTC (`2026-04-20T10:30:00Z`) |
| Simulated time | Float seconds from run start (`sim_timestamp`) |
| Positions | Object `{x, y, z}` in UE5 world units (cm) |
| Rates | Per simulated hour |
| Fractions | 0.0–1.0 (not percentage) |
