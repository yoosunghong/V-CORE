# spec_virtual_process.md — Virtual Process Chatbot Architecture

> This supersedes the prior web-chatbot design in [spec_web.md](spec_web.md),
> [spec_api.md](spec_api.md), and the AGV-only parts of [spec_unreal.md](spec_unreal.md).
> The web stack is now the pai_chatbot-derived LangGraph multi-agent system under `web/`.

## Overview

The web subsystem is a **Virtual Process** digital-twin chatbot (rebranded from the
pai_chatbot "Smart Farm" demo). A natural-language request is turned into a safe,
schema-validated command and executed against the **UE5 AGV cell** (`AGVSimController`
HTTP server on `:7777`). Progress streams back to the chat session live.

## Services (`web/`)

| Service | Role | Port |
|---|---|---|
| `chatbot-backend` | FastAPI + LangGraph multi-agent orchestration, Ollama LLM gateway, UE5 driver | 8000 |
| `chat-web` | React/Vite operator UI (UE5 camera viewport + chat + process dashboard + zone focus) | 5173/5199 |
| `control-server-demo` | Station registry mock (`/cell/status`, `/stations/{id}`) | 8010 |
| `iot-platform-demo` | Legacy IoT mock — **orphaned**, `legacy` profile only (`--profile legacy`) | 8020 |
| `telemetry-collector` | AGV telemetry ingest (`POST /ingest` from backend WS; raw UDP/TCP) → Firebase Realtime Database | 8030 / 9999udp / 9998 |
| `ollama` / `ollama-model` | Local Gemma LLM runtime + model pull | 11434 |
| postgres / redis / qdrant / timescaledb | Data stores (session/command persistence + optional RAG/timeseries) | — |

## Domain model (renamed from Smart Farm)

- `Station` (was `Bed`): `station_id`, `station_type`, `task_ready`, `cell_id`, `zone`, `state`, `accessible`.
- `ProcessTelemetry` (was `SensorSnapshot`): `throughput`, `active_agvs`, `avg_wait_time`, `collision_risk`, `uptime`.
- `RobotCommandName`:
  - Station-targeted: `run_station_task`, `move_to_station`, `inspect_station`, `cancel_command`
  - Sim lifecycle (Virtual Process control): `start_simulation`, `stop_simulation`, `pause_simulation`, `resume_simulation`, `set_sim_speed`
  - **`move_to_station` is internal-only.** It remains a valid contract for internal/agent-plan
    use but is **not user-requestable**: `ToolRouter.user_facing_tools()` (used by
    `OllamaLlmGateway.propose_tool_call`) withholds it from the tool list offered to the LLM, the
    tool-planning prompts no longer map any move verb, and `build_rule_based_tool_call` drops the
    move branch. A user "AGV를 N번으로 보내" request therefore produces no tool call (→ ambiguous
    path); `ToolRouter.ollama_tools()` still includes it for internal callers.

## Backend command + event flow

1. `POST /chat/messages` → `ChatOrchestrator` → `LangGraphMultiResponseAgent` graph:
   `record_user_message → publish_agent_plan → classify_request →`
   `{report_process_status | report_simulation_status | report_available_actions | report_run_comparison | resolve_station → plan_tool_call → finalize_robot_command}`.
2. `classify_request` routes process-status / station-action / compare-runs / robot-command (incl. sim lifecycle)
   **LLM-first**: `ChatOrchestrator._classify_route` calls `LlmGateway.classify_intent`
   (`intent_system`/`intent_user` prompts → `{"intent": ...}`) and emits an `agent.route.selected`
   event carrying `{route, source}` (`source` = `llm` or `keyword`). When the LLM is unavailable,
   times out, or returns an out-of-set value, routing falls back to the deterministic keyword
   classifier, so a flaky Ollama degrades gracefully instead of freezing the turn. The keyword
   fallback treats a simulation/command **action verb**
   (`돌려/돌리/실행/시작/배치/투입/start/run/deploy/정지/속도`…) as taking precedence over a status
   read, so a goal-framed request that also names KPI nouns ("처리량 70 이상, 충돌 0건") still routes
   to `start_simulation`. Likewise `build_rule_based_tool_call` recognizes those verbs and extracts
   `acceptance[]` from the prompt, so AGV deployment + a PASS/FAIL verdict run even when the Ollama
   tool call itself is empty. A **compare** intent (`비교/compare/대비/어느 게 더/뭐가 더 나아`…, but
   never over an explicit sim lifecycle command) routes to `compare_runs`: `_compare_recent_runs`
   pulls the two newest runs with final `kpis_json`, builds an A/B verdict via
   `domain.evaluation.build_run_comparison` (per-KPI winner on the same KPI directions the
   single-run grade uses; an acceptance verdict where exactly one run passed overrides the metric
   tally), emits an `agent.run.comparison` event, and returns a deterministic Korean summary. Needs
   ≥2 finished runs, else it asks the operator to run two sims first.
3. `RobotCommandOrchestrator.issue_robot_command` → `Ue5CommandClient.send_robot_command`
   posts to UE5 `:7777` (see endpoints below). `AUTO_COMPLETE_DEMO_COMMANDS=false` when
   `UE5_CLIENT_MODE=ue5` so completion comes from real UE5 events.
4. UE5 echoes `session_id`/`correlation_id`/`command_id` back to the backend ingest
   (`POST /internal/ue5/events` or `WS /internal/ue5/stream`), which converts them to
   `DomainEvent`s on the in-memory event bus keyed by `session_id`.
5. `WS /chat/sessions/{session_id}/events` streams those events to `chat-web` live.
6. Completion/failure events (`robot.command.completed`/`failed`) run through
   `ChatOrchestrator.handle_completion_event`, producing a `ReportAgent` chat report.

## Live simulation status (`simulation_status` route)

A mid-run "현재 상태는? / AGV 상태 / how is it going" question routes to `simulation_status`
(graph node `report_simulation_status`), a **read-only** route that does **not** dispatch to UE5.
It reads the live `LiveTelemetryHub` (the cache fed by the UE5 WebSocket stream) — per-AGV `state`
plus the process frame `uptime` — and reports the number of operating AGVs, each AGV's state, the
cell **work rate (= process `uptime` %)**, and any AGVs in `STOPPED_COLLISION`. AGVs whose state
starts with `MOVING` or is `LOADING`/`UNLOADING`/`WAITING_AT_SECTION` count as operating; `IDLE`/
`STOPPED_OPERATION` are idle/stopped. `ChatOrchestrator._is_simulation_status_request` is a
deterministic keyword check that runs in `_classify_route` ahead of the LLM (and below the explicit
sim-command guard so "시뮬레이션 시작/정지" still routes to the command path); it wins over the
KPI-only `process_status` read. With no live data it replies that no simulation is running.

## Collision halt → terminate + report

When **every** AGV in a run is stopped on a collision, UE5 `AAGVSimController` detects it
(`AllSpawnedAgvsCollisionStopped()`, checked each Tick after `CheckAgvProximityCollisions`) and
ends the run once via the existing `CompleteRuntimeRun("collision_halt")` path — no new transport.
That emits the normal `robot.command.completed` event with `payload.stop_reason="collision_halt"`
and final `kpis` (including the collision count). The backend's existing ingest records the run as
terminated and `handle_completion_event` produces the report; `ReportAgent` prepends a deterministic
collision-halt notice (with the collision count) so the chatbot always reports the collision
alongside the end-of-run results.

## Agentic optimization loop (goal-seeking AGV count)

The `optimize_agvs` route turns the chatbot from a one-shot command dispatcher into a
**goal-seeking agent**: a closed `observe → judge → decide → act → re-observe` loop that searches
for the configuration satisfying an operator goal, instead of running exactly what was typed once.

- **Trigger.** `ChatOrchestrator._is_optimize_request` matches an optimize verb
  (`최적/최적화/찾아/optimize/optimal`…) together with the bottleneck metric (`병목/bottleneck`). This
  deterministic check runs in `_classify_route` ahead of the LLM (like the compare check), so the
  loop fires reliably without depending on Ollama. Route → graph node `optimize_agv_count`.
- **Goal.** `domain.optimization.parse_optimization_goal(text, max_count)` extracts the target
  metric (`bottleneck_rate`), comparator (default `<=`), threshold (the `NN%` in the text, default
  `30`), and the search bounds (`min_count=1`, `max_count`). The upper bound is **not hardcoded**:
  `_run_agv_optimization` first calls `_resolve_max_agv_count`, which reads the cell's authored fleet
  size live from UE5 `/sim/status` (`max_agvs` = `AuthoredAgvs.Num()`), falling back to the
  `AGV_FLEET_MAX` setting (default 5) only when UE5 is unreachable or doesn't report it. The
  planning process surfaces this as an explicit "UE5 셀에 배치된 최대 AGV 대수를 조회" step
  (`_OPTIMIZE_PLAN_STEPS`).
- **The loop — two execution modes (dispatched in `_run_agv_optimization`).**
  - **Live UE5 (default when `auto_complete_commands` is off, i.e. `UE5_CLIENT_MODE=ue5`).**
    `_run_agv_optimization_live` runs each candidate as a *real* simulation: it issues
    `start_simulation` (agv_count, short `duration=_OPTIMIZE_RUN_DURATION_SEC`) to UE5 `:7777`, then
    **awaits that run's actual `robot.command.completed` event** off the per-session event bus
    (`_await_run_completion`, correlated by `command_id`, with `_OPTIMIZE_RUN_TIMEOUT_SEC` guard),
    reads the **real bottleneck rate from the run's congestion heatmap** (UE5's
    `CompleteRuntimeRun`/`BuildRuntimeReport` emits `heatmap_grid`; the rate is derived at the
    `ue5_ingest` boundary so every real run carries it), judges the goal, and decides the next
    candidate. Because this spans many real runs it runs as a **background task** — the chat turn
    returns an immediate acknowledgement and progress/report stream back as events + a chat message
    (`chat.report.generated`). UE5 runs one sim at a time, which the sequential loop respects.
  - **Offline model (fallback when UE5 is not live / mock mode).** `_run_agv_optimization_model`
    iterates the same way but scores each candidate with `domain.process_model.simulate_run_kpis(n)`,
    a deterministic process model (no UE5 round-trip), so the demo still works and stays reproducible.
  Both share the pure search (`search_optimal_agv_count` in `domain.optimization`): candidates run
  `max_count` **down** to `min_count`, and because the bottleneck rate is monotonic in AGV count the
  first (highest) candidate that satisfies the goal is the optimum, so the loop stops there.
- **Bottleneck-rate metric.** `domain.process_model.bottleneck_rate_from_heatmap(grid, res_x, res_y)`
  is the single source of truth: the fraction of heat-grid cells at ≥60% of peak density (the
  congested "hot" cells), expressed as a percent. This reuses the heatmap hot-fraction calculation
  already used by `evaluation._heatmap_stats` and mirrors the UE5 `UCongestionHeatmapComponent`
  density grid. It is added to the run `kpis` as `bottleneck_rate`, to the single-run
  `build_simulation_evaluation` (lower is better), to the A/B `build_run_comparison`, and to the F4
  `acceptance[]` metric enum.
- **Sub-tasks are real runs.** Each iteration persists a `Simulation` + completed `SimulationRun`
  (with `kpis_json`) and emits `simulation.created` / `simulation.run.updated`, so every candidate
  shows up in the run list and history exactly like a manually-launched sim, and the chosen optimum
  is directly comparable. Per-iteration progress is published as `agent.optimize.started` /
  `agent.optimize.iteration` / `agent.optimize.completed` events for the live event stream.
- **Report.** The loop returns a deterministic Korean report listing every candidate it tried
  (count → bottleneck rate → key KPIs → 충족/미달) and the chosen optimum (or an infeasible-goal
  message suggesting a relaxed threshold).

## Enterprise UE5 viewport architecture

The web frontend no longer assumes a prototype overlay with UE rendered behind it.
The UE camera feed is an explicit browser surface:

- **Video/camera transport:** UE Pixel Streaming WebRTC viewer, configured by
  `UE5_VIEW_URL` and exposed to the frontend by `GET /unreal/viewport`.
- **Telemetry transport:** backend-owned SSE endpoint, `GET /unreal/telemetry/stream`. While a
  sim is live it replays the cached UE5 frames as `event: agvs`/`process`/`hud` (the
  `LiveTelemetryHub`); otherwise it falls back to `event: telemetry` from the IoT mock. See
  "Live SSE feed" below.
- **Command transport:** backend-to-UE remains HTTP (`/sim/*`, `/agv/command`) with
  `X-AGV-API-Key`; UE-to-backend progress remains HTTP webhook or internal WebSocket.
- **Data-oriented boundary:** browser state consumes compact DTOs (`ProcessTelemetry`,
  `UnrealViewport`) rather than UE actor objects. UE actor state is reduced to KPI,
  command, and session-correlated event records at integration boundaries.

`chat-web` renders the configured Pixel Streaming page as the full-bleed main viewport
and overlays operator controls. If Pixel Streaming is not running, the dashboard and
SSE telemetry still remain usable, making video failure independent from command and
status observability.

For the local packaged demo, `Scripts\LaunchPixelStreaming.bat` expects Epic's
Pixel Streaming 2 WebServers runtime at `PixelStreaming2WebServers/` in the repo root
(`SignallingWebServer/package.json` must exist). The batch builds the local Node packages
when `SignallingWebServer/dist/index.js` is missing, starts the signalling/player server
with streamer WebSocket port `8888` and player HTTP port `8880`, and launches UE with
`-PixelStreamingURL=ws://127.0.0.1:8888`. `UE5_VIEW_URL` must point at the browser player
page, `http://localhost:8880`, not the streamer WebSocket port.

## UE5 endpoints (`AGVSimController`, port 7777)

All accept `X-AGV-API-Key`. Command bodies carry `session_id`, `correlation_id`,
`command_id`, `command_name`, and a nested `parameters` object.

| Method | Path | Purpose |
|---|---|---|
| POST | `/sim/start` | Start a run (`parameters`: `agv_count`, `speed_multiplier`, ...) |
| POST | `/sim/stop` | Stop the running simulation |
| POST | `/sim/pause` | Pause (global time dilation → 0) |
| POST | `/sim/resume` | Resume (restore speed multiplier) |
| POST | `/sim/speed` | Set speed multiplier (`parameters.speed_multiplier`) |
| POST | `/agv/command` | `move_to_station` / `run_station_task` / `inspect_station` (`parameters.station_id`, optional `parameters.agv_id`) — retargets a spawned AGV to the station anchor; `robot.command.completed` fires on arrival |
| GET | `/sim/status` | Live KPIs → `ProcessTelemetry` JSON (incl. `progress_percent`) |
| POST | `/camera/select` | Switch the viewport to an AGV's chase camera (`{ agv_id }`, or `"overview"`) |

UE5 posts chat-correlated events back to the backend at `POST /internal/ue5/events`, and
fans per-AGV + process telemetry out as UDP datagrams to the telemetry-collector (below).

## PC safety and observability boundary (2026-06-19)

The chat boundary now has a compact backend guardrail layer before LangGraph and before any
assistant text is stored or returned:

- `SafetyGateway` sanitizes user and assistant text by removing script/style blocks, stripping
  HTML tags, collapsing control characters, and redacting common PII patterns (email, phone
  number, Korean resident-registration number, and API/bearer-key shaped secrets).
- Obvious off-domain or hostile requests are refused before the LangGraph turn starts. The
  refusal is stored as a normal assistant message and emitted with a redacted `safety.refused`
  event so the UI still has an auditable turn.
- Retrieved RAG/GraphRAG chunks are treated as untrusted data. Before prompt injection they are
  PII-redacted and instruction-like phrases (`ignore previous`, `system prompt`, `developer
  message`, etc.) are replaced with neutral `[retrieved-instruction-redacted]` markers.
- `InMemoryEventBus` redacts event payloads before storing/fanning them out. Operator events still
  show route/retrieval/command facts, but logged text does not contain PII or secrets.
- `TurnTraceSink` publishes an `agent.turn.traced` event at the end of each LangGraph turn with an
  OTel-shaped span payload: route, node sequence, retrieval hit count, approximate input/output
  token counts, latency, and low-grounding/misroute bucket hints. The current sink is local and
  dependency-free; it is the handoff point for Langfuse/OTel export in a deployed environment.

## Chat session API (`chatbot-backend`, port 8000)

| Method | Path | Purpose |
|---|---|---|
| POST | `/chat/sessions` | Create a chat session |
| GET | `/chat/sessions` | List sessions (only those with messages) |
| GET | `/chat/sessions/{session_id}/messages` | Load session history |
| DELETE | `/chat/sessions/{session_id}` | Delete a session and its messages/commands (204; 404 if unknown) |
| POST | `/chat/messages` | Send a user message and receive the assistant reply + events |
| WS | `/chat/sessions/{session_id}/events` | Live domain-event stream for the session |

`DELETE` removes the session, its `chat_messages` (FK cascade), and its `robot_commands`
(deleted explicitly — no cascade). The `chat-web` session list deletes the active session
by falling back to the next session or opening a fresh one.

## Browser-facing Unreal endpoints (`chatbot-backend`, port 8000)

| Method | Path | Purpose |
|---|---|---|
| GET | `/unreal/viewport` | Returns `stream_url`, transport metadata, and `telemetry_sse_url` for the UE camera surface |
| GET | `/unreal/telemetry/stream` | SSE: live `agvs`/`process`/`hud` frames during a sim (from `LiveTelemetryHub`), else `telemetry` fallback |
| POST | `/unreal/cameras/{agv_id}/select` | Proxies a camera switch to UE5 `/camera/select` (best-effort) |

## Scenario and playback API

The operator UI owns scenario definitions through the backend. The backend/PostgreSQL is
the canonical store for scenario configuration and run records; UE5 is the live runtime
authority for movement, collision/bottleneck detection, and KPI calculation; Firebase and
WebSocket/SSE streams are realtime projections only.

Scenarios use the single authored UE level and vary runtime parameters instead of loading
one level per simulation. This keeps the demo path small and matches the current UE5
`/sim/start` contract.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/scenarios` | List saved scenario configurations |
| POST | `/api/v1/scenarios` | Create a scenario |
| PUT | `/api/v1/scenarios/{scenario_id}` | Update a scenario |
| DELETE | `/api/v1/scenarios/{scenario_id}` | Delete a scenario and its run history |
| POST | `/api/v1/scenarios/{scenario_id}/duplicate` | Copy a scenario with a new name |
| POST | `/api/v1/scenarios/{scenario_id}/run` | Create a run and proxy UE5 `/sim/start` |
| GET | `/api/v1/scenarios/{scenario_id}/runs` | List runs for one scenario |
| POST | `/api/v1/runs/{run_id}/pause` | Proxy UE5 `/sim/pause` and mark run paused |
| POST | `/api/v1/runs/{run_id}/resume` | Proxy UE5 `/sim/resume` and mark run running |
| POST | `/api/v1/runs/{run_id}/stop` | Capture latest status, proxy UE5 `/sim/stop`, and mark run stopped |
| POST | `/api/v1/runs/{run_id}/speed` | Proxy UE5 `/sim/speed` with a new multiplier |
| GET | `/api/v1/runs/{run_id}/result` | Return saved final KPIs or the latest live snapshot |

`POST /api/v1/scenarios` body:

```json
{
  "name": "10 AGVs / 1.5x",
  "agv_count": 10,
  "speed_multiplier": 1.5,
  "workload_percent": 120,
  "policy_id": "POLICY_FIFO",
  "duration_seconds": 600,
  "bottleneck_threshold_sec": 10
}
```

`POST /api/v1/scenarios/{scenario_id}/run` creates `run_id` first, then sends UE5:

```json
{
  "run_id": "<run_id>",
  "session_id": "scenario-control",
  "correlation_id": "corr_<...>",
  "command_id": "<run_id>",
  "command_name": "start_simulation",
  "parameters": {
    "agv_count": 10,
    "speed_multiplier": 1.5,
    "duration": 600,
    "policy_id": "POLICY_FIFO",
    "bottleneck_threshold_sec": 10,
    "workload_percent": 120
  }
}
```

When UE5 later emits `robot.command.completed` with `payload.run_id` and `payload.kpis`,
the backend stores those KPIs on the matching `SimulationRun`.

### Chat-driven scenarios mirror into the scenario list

A simulation the operator launches **from chat** is registered in the same scenario/run
store as a manually-authored one, so the scenario list side tab and its run history show
chat-started and panel-started runs identically. This is handled in
`ChatOrchestrator._sync_scenario_lifecycle`, called by the LangGraph
`finalize_robot_command` node right after `issue_robot_command`, and keyed off
`SIM_LIFECYCLE_COMMANDS`:

- `start_simulation` → `create_scenario` (name `챗봇 시나리오 · AGV {n}대 ({MM-DD HH:MM})`,
  built from the tool-call `parameters`: `agv_count`, `speed_multiplier`, `duration`,
  `policy_id`, `workload_percent`, `bottleneck_threshold_sec`) + a `SimulationRun`
  (`status=running`, `ue_run_id=command_id`). Emits `scenario.created`.
- `stop/pause/resume/set_sim_speed` → resolves the latest active run via
  `_latest_active_run` (newest `starting|running|paused` across the repository, so a chat
  stop drives a panel-started run too) and updates its status / speed. Emits
  `scenario.run.updated`.

Both events carry `{scenario_id, run_id, status, source:"chat"}` and ride the chat
response + the session event WebSocket. The `chat-web` overlay listens for them and calls a
non-destructive `reloadScenarioList()` (refreshes the list + selected run history without
clobbering an in-progress config draft), so a chatbot run appears in the side tab live.

Manual control from the list is unchanged: the operator can still create/edit/duplicate a
scenario and drive `run/pause/resume/stop/speed` from the config panel.

**Routing guard.** `_classify_route` overrides the LLM intent to `robot_command`
(`source="llm_guard"`) when `_is_explicit_sim_command` matches — a sim topic word
(`시뮬레이션`/`simulation`/`sim`/`agv`) plus a lifecycle verb
(`시작`/`정지`/`멈춰`/`재개`/`돌려`/`start`/`stop`/`pause`/`resume`/`run`/…). This stops Ollama
from occasionally misrouting an explicit "시뮬레이션 시작/정지" command to a read/query intent
(which would drop the command before it registered a scenario). A bare KPI/status question has
no lifecycle verb, so the guard never hijacks it.

### F4 Scenario Verification (acceptance criteria → verdict)

The `start_simulation` tool contract accepts an optional `acceptance[]` array of
`{metric, comparator, threshold, label?}` (metrics: `throughput`, `avg_wait_sec`, `collision_count`,
`uptime_ratio`, `active_agvs`; comparators `>=`/`<=`/`==`). `ToolRouter` validates and normalizes it,
then it rides through `parameters` to UE5 `POST /sim/start`. The engine evaluates the criteria against
the final KPIs and returns a `verdict` (`passed`, `checks_total`, `passed_labels`, `failed_labels`) on
the `robot.command.completed` payload (alongside `kpis`). `handle_completion_event` → `ReportAgent`
surfaces the PASS/FAIL in chat — the LLM report sees `verdict`+`kpis` (whitelisted in
`_compact_event_context`) and the rule-based fallbacks append `format_verdict_summary(...)`. See
[spec_portfolio_features.md](spec_portfolio_features.md) §5 and
[guide_unreal_editor_f4_hud.md](guide_unreal_editor_f4_hud.md).

## Real-time Telemetry & Multi-AGV Monitoring

A dedicated pipeline streams per-AGV state to a Firebase Realtime Database that the
dashboard subscribes to directly, powering the camera switcher, per-camera HUD overlay,
and the all-AGV monitor grid.

```
UE5 AGVSimController ──WebSocket JSON──▶ chatbot-backend ──HTTP /ingest──▶ telemetry-collector ──firebase-admin──▶ Firebase RTDB ──web SDK──▶ chat-web
  (ws://backend/internal/ue5/stream)     (in-Docker)        (:8030)                              /cells/{cell_id}/...      (onValue)
```

- **UE5** (`AAGVSimController::EmitTelemetry`, 5 Hz): for each spawned AGV sends an `agv`
  payload and one `process` aggregate payload (reuses `BuildStatusJson`).
  `[AGVSim] TelemetryTransport=ws` (default) streams each node over the **same backend
  WebSocket** used for sim events (`SendTelemetryWebSocketPayload`); the backend forwards
  it to the collector inside Docker. This is **required on Windows**: UE5 raw-socket
  `udp`/`tcp` to the published collector ports connects but Docker Desktop's proxy silently
  drops the bytes. `tcp`/`udp`/`both` still emit raw newline-JSON/datagrams to
  `TelemetryHost:TelemetryTcpPort`/`TelemetryUdpPort` (use off Docker Desktop Windows).
  `/camera/select` calls `SetViewTargetWithBlend` to the AGV's `UCameraComponent`.
- **chatbot-backend** (`interfaces/ue5_ingest.py`): the `/internal/ue5/stream` WebSocket
  routes frames with `kind` in `{agv, process}` (and no `event_type`) to
  `POST {TELEMETRY_COLLECTOR_URL}/ingest`; all other frames stay on the event path.
- **telemetry-collector** (`web/services/telemetry-collector`): asyncio UDP + TCP servers
  **and** `POST /ingest` (FastAPI lifespan) parse nodes and write `firebase-admin` nodes.
  No-ops if `FIREBASE_DB_URL` is unset. `GET /health`, `GET /debug/latest`.
- **chat-web** (`src/firebase.ts`): `subscribeAgvs` / `subscribeProcess` via `onValue`;
  HUD + AGV List + metric cards + progress bar bind to the live nodes. Falls back to
  the SSE/overlay path when `VITE_FIREBASE_DATABASE_URL` is empty.

### Live SSE feed — Firebase-independent path (2026-06-08)

The Firebase leg (collector → RTDB → web SDK) is the **secondary** path. The **primary** live
feed is now Firebase-independent: the backend caches the AGV/process/HUD frames it already
receives over the UE5 WebSocket and replays them to the overlay over the existing SSE.

```
UE5 ──WS JSON──▶ chatbot-backend (LiveTelemetryHub) ──SSE──▶ chat-web
                 ue5_ingest.py → application/live_telemetry.py   GET /unreal/telemetry/stream
```

- **`application/live_telemetry.py` (`LiveTelemetryHub`)**: `ue5_ingest.py` calls
  `hub.ingest(frame)` for every `kind:{agv,process}` frame (in addition to forwarding to the
  collector). Frames older than 5 s are treated as stale (UE5 sends no `running:false` frame on
  stop), so the feed reports an empty cell once a run ends.
- **`GET /unreal/telemetry/stream`**: while the hub has live data it emits `event: agvs`
  (list), `event: process` (snapshot), and `event: hud` (HUD snapshot). With no live sim it
  falls back to `event: telemetry` (the IoT-mock process row) so the metric cards still render.
- **chat-web** (`App.tsx`): the SSE listeners for `agvs`/`process`/`hud` populate the AGV list,
  the metric cards, and the **web HUD**. The Firebase subscriptions remain but only augment
  (never clear) this feed. **This is what fixes the stuck "실시간 AGV 텔레메트리를 기다리는 중입니다."
  empty-state**: the AGV list no longer depends on the fragile Firebase delivery during a run.
- **Web HUD** (`VcoreHud` in `App.tsx`): renders the `hud` frame top-left of the viewport —
  status, speed/progress/policy, progress bar, tasks/collisions counters, verdict badge, and a
  recent-events ticker. This replaces the removed in-viewport UE5 HUD (spec_unreal §7.1). The
  HUD fields ride the `kind:"process"` frame from `AAGVSimController::EmitTelemetry`
  (`tasks_completed`, `collisions`, `policy_id`, `recent_events`, `verdict_summary`,
  `verdict_passed`).

### ReportAgent narrative evaluation (2026-06-10)
- **Backend-authored qualitative narrative.** `app/domain/evaluation.py`
  `build_simulation_evaluation(kpis, verdict)` produces a graded `SimulationEvaluation` (heatmap
  concentration/hotspot + per-KPI notes) using the **same thresholds** as the frontend
  `buildAiEvaluation` — keep the two in sync. `ReportAgent.generate_report` feeds
  `evaluation.to_prompt_block()` to `LlmGateway.generate_report(..., evaluation=...)`; the
  `report_system` prompt tells the model to add a **separate "AI 종합 평가" narrative section**
  that weaves the heatmap analysis and KPI qualitative notes into flowing Korean prose. Rule-based
  and LLM-error fallbacks append `evaluation.to_narrative()` so the section is always present. The
  narrative rides the existing `chat.report.generated` `content`; the structured graded
  `AiEvaluationCard` (client-side) renders alongside it.

### Studio result cards + AI evaluation (2026-06-10)
- **Result report mirrored into Simulation Studio.** On completion the run persists
  `kpis_json` (incl. `heatmap_grid`/`heatmap_res_x|y`) and `result_json` (the full UE5 payload
  incl. `verdict`). Each finished row in the **실행 기록 (run history)** list (`.simRunRow`) is now
  an expandable button; expanding reconstructs the same result card shown in chat — verdict
  banner + chips + KPI grid + heatmap + AI evaluation — from those persisted fields (no extra
  API call). Live/in-progress rows are not expandable.
- **Run-status banner colors.** `.simRunRow` carries `data-status`; a left accent + tint marks
  state: starting/running **blue**, completed **light green**, paused amber, failed red. The
  active run additionally gets a focus ring.
- **AI overall evaluation (`buildAiEvaluation` / `AiEvaluationCard` in `App.tsx`).** A pure,
  deterministic analysis turns the final KPIs + verdict into a qualitative assessment beyond the
  raw numbers: a graded headline (A 우수 / B 양호 / C 주의) plus per-metric notes. Heatmap analysis
  computes the congestion **concentration ratio** (peak/mean), **hot-cell fraction**, and
  **hotspot quadrant** to report whether congestion is locally concentrated (bottleneck risk) or
  evenly distributed. Rendered inside both the chat `ReportCard` and the Studio result detail so
  the two stay identical.

### Overlay layout (2026-06-05)
The operator overlay was trimmed to the live telemetry it can actually drive:
- **Left metric stack** drops the *Collision Risk* card (no live source); the rest stay.
- The bottom *Load / Work / Unload* workload strip was removed (it was driven by a
  cosmetic chat-event progression, not real process state).
- The top center feed is now an **ephemeral work-log stack**: each robot/tool domain
  event becomes a toast that fades out and is removed after 5 s (`logToasts` in `App.tsx`).
- The per-AGV **HUD** (battery / current status / speed / destination / load) is anchored
  at the **bottom** and only shows once an AGV is selected.
- The floating camera tab-bar was replaced by an **AGV List** button (was "전체 AGV 모니터")
  that opens the AGV banner list (name, battery, operating status); selecting a banner calls
  `/unreal/cameras/{id}/select` and shows that AGV's HUD.
- **ZONE 1** is the default view and maps to the UE5 main camera: pressing it releases any
  per-AGV camera (`selectAgvCamera("overview")`) and returns to the main render.
- **Conditional viewports & metrics**:
  - The UE5 player `iframe` and its status strip/HUD display are only rendered when the simulation is active (`starting`, `running`, or `paused`). When the simulation is stopped or inactive, a clean blank grid background is shown instead.
  - The zone navigation controls (`ZONE 1`, `ZONE 2`, `ZONE 3`) and the **Throughput** metric card are also hidden when the simulation is inactive, and appear only within the active simulation lifecycle.
- **Repositioned player controls**:
  - The default Pixel Streaming player controls (`#controls` containing Full Screen, Settings, and Information buttons) have been moved to `top: 60px; left: 270px;` to the right of the `.leftStack` (metric panels) and below the `.topBar` header, preventing them from overlapping with the "Process Intelligence" system card.

### Viewport, zone cameras & UI refresh (2026-06-08)
- **Viewport renders on sim start (incl. chat-driven runs).** `isSimActive` in `App.tsx` is
  no longer gated on a frontend `activeRun`. It is now true when **any** of: an `activeRun`
  is `starting/running/paused`, Firebase `process.running === true`, or a chat run has begun.
  The chat path sets a `chatSimActive` flag the moment a sim-driving domain event arrives
  (`robot.command.requested/accepted`, `robot.moving`, `robot.working`); it clears on
  `POST /api/v1/runs/{id}/stop` or when telemetry reports `process.running === false`. This
  fixes the case where typing "Run simulation …" in chat left the UE iframe hidden.
- **ZONE 1/2/3 buttons drive three real cameras.** The zone nav now calls
  `selectAgvCamera("zone-1"|"zone-2"|"zone-3")` (proxied by `POST /unreal/cameras/{id}/select`
  → UE `POST /camera/select` with `{agv_id:"zone-N"}`) instead of the no-op
  `POST /unreal/zones/{id}/focus`. In UE, `AAGVSimController::SelectViewTarget` resolves
  `zone-1/2/3` to `ACameraActor`s via `FindZoneCamera(FName)`, which matches an actor **Tag**
  (`Zone1`/`Zone2`/`Zone3`) or the actor name. `zone-1`/`overview` re-enable the F3 auto
  director; `zone-2`/`zone-3` suspend it. **Editor setup:** place/select the three Process-level
  cameras and add the tag `Zone1`/`Zone2`/`Zone3` to each (or name them so the name contains it).
- **AGV list auto-shows during a run.** The AGV List panel (`AgvMonitorGrid`) opens
  automatically while `isSimActive` and stays open after a selection so the operator can hop
  between per-AGV chase cameras; each click calls `/unreal/cameras/{id}/select`.
- **Chat session list**: rows are thinner (`.sessionOpen` padding trimmed) and the row title
  now shows the distinguishing **first user message** instead of the long shared prefix, so
  older sessions are identifiable; the list scrolls within the side tab.
- **Simulation Studio split**: the left `.simSideTab` now shows **only** the scenario list and
  the **실행 기록 (run history)**, each in its own scroll area (`.simScenarioList` /
  `.simRunList`, `max-height` + `overflow-y`). The **Configuration** form + playback/speed
  controls moved to a separate right-docked `.simConfigTab` that opens when a scenario row is
  selected or "+ 추가" is pressed.

### Operator UI refresh (2026-06-07)
- **Chat session list**: rendered as bordered, tightly-spaced rows (`.sessionRow`) instead
  of far-apart borderless titles. Each row has an open button (`.sessionOpen`) and a
  trash-icon delete button (`.sessionDelete`) wired to `DELETE /chat/sessions/{id}`.
  Deleting the active session switches to the next session or opens a fresh one.
- **Simulation Studio side tab**: the top-left hamburger is now a toggle button that opens a
  left-anchored side tab (`.simSideTab`) holding the full simulation UI. The old always-on
  floating `.scenarioPanel` was removed. The side tab is organized into sections: a
  scenario list with per-row delete + an "+ 추가" add button, a config form, playback /
  speed controls, and an **실행 기록 (run history)** list showing each past run's status and
  KPIs (throughput / wait / speed) for reviewing previous simulation results.
- **Collapsible metric cards**: *Process Progress* (`.progressRate`) and every left-stack
  metric card (Uptime/Availability, Avg Wait/Queue Delay, Throughput, …) carry a `+`/`–`
  collapse button (`.cardCollapse`); collapsed cards hide their value body and shrink.

### Firebase RTDB layout
```
cells/{cell_id}/agvs/{agv_id}  = { cell_id, agv_id, battery, speed, state, destination,
                                   carrying_load, completed_tasks, position{x,y,z}, ts }
cells/{cell_id}/process        = { cell_id, running, paused, speed_multiplier, throughput,
                                   active_agvs, avg_wait_time, collision_risk, uptime,
                                   progress_percent, ts }
```

### Firebase project setup (demo)
1. Create a Firebase project + enable **Realtime Database**.
2. telemetry-collector (server writes): download a service-account JSON → place at
   `web/secrets/firebase-sa.json` (git-ignored); set `FIREBASE_DB_URL` in `web/.env`.
3. chat-web (browser reads): copy the web app config into `VITE_FIREBASE_*` in `web/.env`.
4. Keep `CELL_ID` aligned across UE5 `[AGVSim] CellId`, the collector, and the dashboard.

## Configuration (env)

- `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL=gemma4:e2b`
- `CONTROL_SERVER_CLIENT_MODE=http|mock`, `CONTROL_SERVER_BASE_URL`
- `UE5_CLIENT_MODE=ue5|mock`, `UE5_BASE_URL=http://host.docker.internal:7777`, `UE5_VIEW_URL=http://localhost:8880`, `AGV_API_KEY`
- `AUTO_COMPLETE_DEMO_COMMANDS` (auto-completes commands in mock mode)
- The UE5 `AGV_API_KEY` and the UE editor's `Config` `[AGVSim] APIKey` must match for the
  ingest webhook to authenticate.

## Known follow-ups
- `/agv/command` now retargets a spawned AGV to the resolved station anchor: the controller
  picks the AGV (optional `parameters.agv_id`, else the first available), resolves `station_id`
  to a ratio along that AGV's path spline, and drives it there via `AAGVActor::DirectToStation`.
  `robot.moving` fires immediately; `robot.command.completed` fires when the AGV reaches the
  anchor (`AAGVSimController::OnAgvReachedStation`). When no sim is running / no AGV is free,
  it falls back to emitting `robot.command.completed` immediately so the chat turn still closes.
- On this Windows Docker Desktop setup, UE5 **raw-socket** telemetry (both UDP to `9999/udp`
  and TCP to `9998`) does not reach the collector: the socket connects/sends "successfully"
  but the Docker Desktop proxy drops the bytes (the in-container connection stays idle with
  empty rx_queue). External clients (PowerShell `TcpClient`, one-shot and persistent) and
  UE5's **WebSocket** to the backend do work. The telemetry default was therefore moved to
  `TelemetryTransport=ws` (UE5 → backend WebSocket → in-Docker `/ingest`). The raw `tcp`/`udp`
  paths are retained for non-Docker-Desktop hosts.
- Keep HTTP webhook and internal WebSocket event envelopes aligned as new UE event
  types are added.
- `iot-platform-demo` is retained for reference but gated behind the `legacy` compose profile; `data-seeder` remains gated behind the `tools` profile. Neither runs in the default active path.
- KPI comparison / LLM report / approval / PDF features from the old web stack were dropped.
