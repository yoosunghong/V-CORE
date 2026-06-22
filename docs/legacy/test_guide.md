# Test Guide — Virtual Process Chatbot

How to verify the migrated web subsystem and its UE5 integration. Four layers, from
"no dependencies" to "full UE5 PIE". Do them in order; each builds on the previous.

| Layer | What it proves | Needs |
|---|---|---|
| L0 | Backend logic is correct (unit/integration) | Docker |
| L1 | Backend API works end-to-end in **mock** mode | Docker (no GPU, no UE5) |
| L2 | The chat-web overlay UI works | Docker + browser |
| L3 | The agent drives the **real UE5** cell | Docker + UE editor (GPU for Ollama) |

> **No local Python** on this dev machine — everything runs in Docker. `cd web` first.

---

## Modes you can toggle (`web/.env`)

- `LLM_PROVIDER=rule_based` → deterministic, **no Ollama/GPU needed** (great for L0/L1).
  `LLM_PROVIDER=ollama` → real Gemma (needed for natural phrasing; GPU recommended).
- `UE5_CLIENT_MODE=mock` → backend auto-completes commands in-memory (**no UE5 needed**).
  `UE5_CLIENT_MODE=ue5` → backend posts to UE5 `:7777`; completion comes from UE5 events.
- `AGV_API_KEY` must equal the UE editor `Config` `[AGVSim] APIKey` (L3 only).

---

## L0 — Backend unit + integration tests (Docker)

```sh
cd web
docker compose up -d --build chatbot-backend control-server-demo postgres redis
# pytest may not be in the image; install on the fly:
docker compose exec chatbot-backend pip install pytest
docker compose exec chatbot-backend python -m pytest -q
docker compose exec control-server-demo pip install pytest
docker compose exec control-server-demo python -m pytest -q
```

**Expect:** all green. Key cases:
- `tests/test_chat_api.py` — station task issues `run_station_task`; `시뮬레이션 시작` →
  `start_simulation`; `속도 1.5배` → `set_sim_speed{1.5}`; `공정 상태` → telemetry; dashboard
  overlay returns `cell_id=VP-CELL-048-ALPHA`, workloads Loading/Working/Unloading.
- `tests/test_station_scenario.py` — completion/failure events produce a Korean report.
- `tests/test_ue5_client.py` — `Ue5CommandClient` posts to `/sim/start` and maps `/sim/status`
  to `ProcessTelemetry`, with a safe fallback when UE5 is unreachable.
- `tests/test_llm_gateway.py`, `tests/test_control_client.py`, `tests/test_robot_orchestrator.py`.

---

## L1 — Backend API smoke, mock mode (Docker, no GPU/UE5)

Set `LLM_PROVIDER=rule_based` and `UE5_CLIENT_MODE=mock` in `web/.env`, then:

```sh
cd web && docker compose up -d --build
curl -s localhost:8000/health
curl -s localhost:8000/dashboard/overlay | python -m json.tool   # or jq
```

**Expect:** `{"status":"ok",...}`; overlay has `cell_id:"VP-CELL-048-ALPHA"`, metrics incl.
`throughput`, workloads `Loading/Working/Unloading`.

### Chat flows (each returns a JSON `ChatResponse`)

```sh
# Station task — expect status "completed", tool_name run_station_task, station_id 2
curl -s localhost:8000/chat/messages -H 'content-type: application/json' \
  -H 'x-correlation-id: c1' \
  -d '{"message":"2번 스테이션 작업해","idempotency_key":"t1"}'

# Sim lifecycle — expect tool_name start_simulation, message "...시뮬레이션을 시작했습니다."
curl -s localhost:8000/chat/messages -H 'content-type: application/json' \
  -H 'x-correlation-id: c2' -d '{"message":"시뮬레이션 시작해줘","idempotency_key":"t2"}'

# Speed — expect tool_name set_sim_speed, arguments.speed_multiplier 1.5
curl -s localhost:8000/chat/messages -H 'content-type: application/json' \
  -H 'x-correlation-id: c3' -d '{"message":"속도 1.5배로 설정해줘","idempotency_key":"t3"}'

# Process telemetry — expect command_id null, content contains "68.2"
curl -s localhost:8000/chat/messages -H 'content-type: application/json' \
  -H 'x-correlation-id: c4' -d '{"message":"공정 상태 알려줘","idempotency_key":"t4"}'

# Not-ready station — expect command_id null, status "pending_confirmation"
curl -s localhost:8000/chat/messages -H 'content-type: application/json' \
  -H 'x-correlation-id: c5' -d '{"message":"3번 스테이션 작업해","idempotency_key":"t5"}'
```

In each response check `.events[].event_type`, `.status`, `.command_id`, and the
`llm.tool_call.proposed` payload `tool_name`/`arguments`.

### Event ingest webhook (simulates UE5 → backend)

```sh
# Wrong key -> 403
curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/internal/ue5/events \
  -H 'content-type: application/json' -H 'x-agv-api-key: wrong' \
  -d '{"session_id":"s","event_type":"robot.moving","payload":{}}'

# Correct key -> {"status":"received"}  (AGV_API_KEY default dev-agv-key)
curl -s localhost:8000/internal/ue5/events -H 'content-type: application/json' \
  -H 'x-agv-api-key: dev-agv-key' \
  -d '{"session_id":"s","correlation_id":"c","event_type":"robot.moving","payload":{"target_station_id":2}}'
```

---

## L2 — chat-web overlay UI (browser)

Open `http://localhost:5173` (or `:5199`). Verify:
- Header shows **VIRTUAL PROCESS AI COMMAND HUB** and `cell_id`.
- Metric cards show 처리량 / 가동률 / 평균 대기시간 / 충돌 위험도 / 가동 AGV.
- Send the chat phrases from L1; the **AI 코파일럿** panel streams plan steps and the
  reply, and the bottom workflow strip advances Loading → Working → Unloading.
- Click a ZONE button → an "Unreal 구역 전환" event appears (zone-focus stub).

---

## L3 — Agent drives real UE5 (Docker + UE editor)

1. In `web/.env` set `UE5_CLIENT_MODE=ue5`, `UE5_BASE_URL=http://host.docker.internal:7777`,
   `AGV_API_KEY=<key>`, and (for natural phrasing) `LLM_PROVIDER=ollama`. `docker compose up -d`.
2. **Compile** `Source/VCORE/private/AGVSimController.cpp` in the UE editor / Rider.
3. Set the editor `Config` `[AGVSim] APIKey` = the same `AGV_API_KEY`. Assign `AGVActorClass`
   and `AuthoredPaths` on the `AGVSimController` actor.
4. **Start PIE** → log line `HTTP server listening on port 7777`.

Direct UE5 endpoint checks (from host):
```sh
curl -s localhost:7777/sim/status -H 'X-AGV-API-Key: <key>'        # live KPIs JSON
curl -s localhost:7777/sim/start  -H 'X-AGV-API-Key: <key>' -H 'content-type: application/json' \
  -d '{"command_id":"cmd1","session_id":"s","correlation_id":"c","command_name":"start_simulation","parameters":{"agv_count":3,"speed_multiplier":1.0}}'
curl -s localhost:7777/sim/speed  -H 'X-AGV-API-Key: <key>' -H 'content-type: application/json' \
  -d '{"command_id":"cmd2","session_id":"s","correlation_id":"c","command_name":"set_sim_speed","parameters":{"speed_multiplier":2.0}}'
```

Full loop (the real test): in chat-web send "시뮬레이션 시작" → "속도 2배" → "일시정지" →
"재개" → "정지". **Expect:**
- AGVs spawn and move in PIE; speed change visibly scales motion (global time dilation);
  pause freezes, resume continues.
- The chat session receives `robot.command.completed` events (UE5 → `/internal/ue5/events`)
  and a Korean report per command.
- `GET :7777/sim/status` reflects running/paused + speed_multiplier.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Chat replies but `status` stays `pending_confirmation` for sim commands | Phrasing didn't match; with `rule_based` use the exact verbs ("시작/정지/일시정지/재개/속도 N배"). |
| L3: command accepted but nothing in PIE | `AGVSimController` not compiled, PIE not running, or `:7777` blocked. Check the PIE log. |
| L3: PIE acts but chat never completes | `AGV_API_KEY` ≠ UE `[AGVSim] APIKey` → ingest webhook 403; or backend can't reach host (`host.docker.internal` / `extra_hosts`). |
| `ollama-model` never healthy | No GPU / model pull failing. For smoke testing use `LLM_PROVIDER=rule_based`. |
| `pytest: not found` | `docker compose exec chatbot-backend pip install pytest` first. |
| `/agv/command` fires but AGV doesn't move | A sim must be running (so AGVs exist) for the AGV to be driven; with no run the command no-ops and completes immediately. Else confirm the named `parameters.agv_id` isn't a collision-stopped AGV. `robot.command.completed` now fires on arrival, not on accept. |
```
