# DONE.md — VCORE Completed Features

> Summary of all implemented features across phases. Updated after each task completion.
> For pending work, see [PLAN.md](PLAN.md). For next task context, see [NEXT_TASK_PROMPT.md](NEXT_TASK_PROMPT.md).

---

## Cloud deploy: web demo at `v-core.yoosung.dev` via Cloudflare Tunnel (2026-06-15)

Deployment path for the web subsystem as a portfolio demo, with UE5 + Ollama + backend kept
**local**. Decided against running UE5/LLM in the cloud (GPU cost; UE5 rendering needs WebRTC
Pixel Streaming which a plain HTTP tunnel can't carry).

- **Single same-origin tunnel.** The chat-web nginx (`:5173`) already serves the static overlay
  and reverse-proxies `/api`, `/chat` (WS), `/unreal` (SSE), `/dashboard`, `/events`, `/ps` to
  the backend (`:8000`), so one Cloudflare Tunnel hostname (`v-core.yoosung.dev → localhost:5173`)
  covers everything — no `api.*` subdomain, no CORS change, no frontend rebuild. `/internal/ue5/*`
  is not proxied by nginx, so the public edge cannot reach the UE5 ingest routes.
- **Config + runbook.** `web/infra/cloudflared/config.example.yml` (ingress template) and
  [docs/deploy_cloudflare.md](docs/deploy_cloudflare.md) (one-time setup + operating notes).
- **Portfolio link.** The live site (`yoosung.dev`) is the Vite app in `Documents/yoosung-h/portfolio`
  (deployed to GitHub Pages). Added a temporary **v-core** project (`src/data/projects/project5.js`,
  registered in `projects.js`, cover at `static/images/v-core/cover.svg`) with a **Live Demo** card
  link in the detail info panel next to GitHub/Period (`ProjectDetail.jsx`). Portfolio build verified
  green: `/projects/v-core` + `/ko/projects/v-core` route files and the cover image emitted to `dist`.
  Remaining (account/interactive): cloudflared login + tunnel create + DNS route, then push the
  portfolio repo to trigger the Pages deploy.

## Agent tool routing: move gated to internal-only, collision halt, live status (2026-06-14)

Three tool-routing behaviour changes to the Virtual Process chatbot (`web/services/chatbot-backend`).

- **`move_to_station` is no longer user-requestable** (kept as an internal/agent-plan capability).
  Added `ToolRouter.user_facing_tools()` (excludes `move_to_station`) and switched
  `OllamaLlmGateway.propose_tool_call` to it; removed the move branch from
  `build_rule_based_tool_call`; dropped the move verb/rule from both `tool_planning_system.txt`
  prompts; removed the user-facing move example from the available-actions message. The enum,
  contract, validation, and UE5 handler stay intact (`ollama_tools()` still includes it), so the
  v2/SFT benchmarks and any internal use are unaffected. A user "AGV를 N번으로 보내" now produces no
  tool call (ambiguous path).
- **Collision halt → terminate + report.** UE5 `AAGVSimController` now detects when every spawned
  AGV is `STOPPED_COLLISION` (`AllSpawnedAgvsCollisionStopped()`, checked each Tick) and ends the
  run once via the existing `CompleteRuntimeRun("collision_halt")` path (latched by
  `bCollisionHaltCompleted`, reset in `StartRuntimeSimulation`). This reuses the normal completion
  event (`stop_reason="collision_halt"` + KPIs), so the backend records termination and reports it;
  `ReportAgent` prepends a deterministic collision-halt notice with the collision count.
- **Live `simulation_status` route.** A mid-run "현재 상태 / AGV 상태" question now routes to a new
  read-only `report_simulation_status` graph node that reads `LiveTelemetryHub` and reports
  operating-AGV count, per-AGV state, cell work rate (= process `uptime`), and any collided AGVs.
  `ChatOrchestrator` gained the `live_telemetry` dependency (wired from `AppContainer`),
  `_is_simulation_status_request` classifier, and `_simulation_status_message` builder.

Backend verified: full `pytest` green (101 passed; one pre-existing unrelated Windows tmp-dir
permission error in `test_llm_benchmark`). Two tests that encoded the old user-move dispatch were
updated, and a `test_user_move_request_is_not_a_tool_call` test added. Spec:
[docs/spec_virtual_process.md](docs/spec_virtual_process.md). **UE5 build deferred** (Perforce
read-only cleared on `AGVSimController.{h,cpp}`; reconcile + compile in the editor).

## AGV start: round-robin path mapping + drive-to-path approach (no teleport) (2026-06-13)

Fixed the spawn-collision bug where AGVs teleported onto a spline and immediately collided. The
previous nearest-path logic mapped each AGV to whatever spline it sat closest to, so (e.g.) 3 of 5
AGVs landed on the same path at the same point and tripped the proximity collision check on frame
one; the remaining units followed and collided too.

- **Round-robin path mapping (even distribution).** `InitializeRuntimeSimulationActors` now maps
  active AGVs to the valid paths via `Slot % PathCount`, so 5 AGVs over 3 paths spread 2,2,1 instead
  of clustering. AGVs sharing a path get an entry distance spaced evenly along the spline
  (`SplineLength * SlotOnPath / UnitsOnPath`), so same-path units never share an entry point. The
  per-AGV nearest-path helper `FindClosestSplinePoint` was deleted.
- **Drive-to-path approach (kills the teleport).** AGVs no longer snap onto the spline at
  `Configure`/`StartRun`. Each AGV starts at its authored home pose and, once moving, drives in a
  straight line to its assigned entry point (`UAGVMovementComponent::TickApproach`, gated by
  `bApproachActive`); on arrival it locks onto the spline and the normal follower takes over.
- **Stagger 1.0 → 3.0 s.** `AgvStartStaggerSeconds` default raised to 3.0 so units begin their
  approach well apart in time.
- **Legacy cleanup.** Removed the dead `UAGVMovementComponent::ResetToDistance`, the now-unused
  `AAGVActor::GetAuthoredLocation()`, and the `FindClosestSplinePoint` projection helper.

Spec: [docs/spec_unreal.md](docs/spec_unreal.md) §5.1.2.1. **Build deferred** (Perforce read-only
cleared; reconcile + compile in the editor).

## AGV start: highest-index selection, nearest-path connection, staggered launch (2026-06-13)

Reworked how the pre-placed AGVs connect to paths at sim start. The original 1:1 AGV↔path pairing
put every AGV at spline distance 0, so units **teleported to their path's origin** and overlapping
ones tripped the proximity collision check immediately. AGVs stay pre-placed and are never
spawned/destroyed; the change is all in `AGVSimController` + a getter on `AAGVActor`.

- **Active selection = highest indices.** `InitializeRuntimeSimulationActors` activates the top
  `agv_count` entries of `AuthoredAgvs` (running 3 of 5 → indices 2–4); the lower indices reset to
  `STOPPED_OPERATION`. Auto-discovery pulls **all** level-placed `AAGVActor`s into `AuthoredAgvs`
  (no longer capped at the path count).
- **Nearest-path connection, start in place (fixes the teleport).** Each active AGV is matched to
  the path whose spline is closest to its editor-placed position (new `AAGVActor::GetAuthoredLocation()`,
  from the `AuthoredTransform` captured at `BeginPlay`), via a sampling projection helper
  `FindClosestSplinePoint`. Its start distance is the point on that spline nearest its placed spot,
  so it rolls forward from where it was deployed instead of jumping to the spline origin. A path may
  carry multiple AGVs; only ≥ 1 path is required (the old "paths ≥ agv_count" gate is gone). The
  earlier `AgvStartSpacing` offset (which itself caused the teleport-from-origin) was removed —
  AGVs placed apart project to distinct distances naturally.
- **Staggered launch.** `StartRuntimeSimulation` starts the first AGV immediately and each later one
  `AgvStartStaggerSeconds` (new `EditAnywhere` property, default 1.0) apart via one-shot timers;
  since an AGV is only dispatchable after `StartRun` sets `bRunActive`, movement is staggered too.
  Timers are guarded on `bSimRunning && !bSimPaused` and cleared on stop.
- `/sim/status` `max_agvs` is now `level AGV actors` (when ≥ 1 path exists) rather than
  `min(AGV actors, paths)`, reflecting that paths hold multiple AGVs.

Spec: [docs/spec_unreal.md](docs/spec_unreal.md) §5.1.2.1. **Build deferred** (Perforce read-only
cleared; reconcile + compile in the editor).

## Plan length tied to task complexity + AGV auto-discovery (2026-06-13)

Follow-up fixes after the live max-AGV / plan-streaming work:

- **Plan length now reflects the task, not a fixed 5 steps.** The planning step ran before
  routing and went straight to the local LLM, which padded every request to ~5 steps and leaked
  internal route identifiers (e.g. *"command_cancel … 재시도"* repeated 4×). `_publish_agent_plan`
  now uses `_plan_for_request`: cheaply-detected rote intents get a concise deterministic plan —
  **stop/pause/resume/cancel = 2 steps**, start = 3, optimize = 5 — while genuinely variable
  requests (station task/move/inspect, free chat) still get an LLM-judged plan. The plan prompt
  (`plan_system.txt`) was rewritten to forbid route/tool identifiers in the visible steps, ban
  duplicate/padding steps, and size the step count to the request. New `tests/test_agent_plan.py`
  locks in the step counts and the no-identifier-leak rule.
- **AGV count auto-discovery (Issue: 5 paths but still capped at 3).** `AuthoredAgvs` and
  `AuthoredPaths` are independent arrays and a unit needs an entry in both, so adding 5 paths
  without 5 AGV actors left the cell capped by the wired AGV count. `InitializeRuntimeSimulationActors`
  now pulls any level-placed `AAGVActor` not already in `AuthoredAgvs` (name-sorted) up to the path
  count, so placing AGV actors + paths is enough — no manual array upkeep. `/sim/status` `max_agvs`
  now reports `min(level AGV actors, authored paths)` (scanned from the level) instead of just
  `AuthoredAgvs.Num()`, so the optimizer's bound matches the real runnable capacity.
- **A no-count "start" now runs the cell at capacity.** Previously a plain "시뮬레이션 시작" defaulted
  to `agv_count=3`. `_finalize_robot_command` now injects the live cell max (`_resolve_max_agv_count`,
  UE5 `/sim/status` → `AGV_FLEET_MAX` fallback) when a `start_simulation` call carries no `agv_count`,
  so the default tracks the real fleet (5) instead of a fixed 3. An explicit count in the message
  still wins.

---

## Live max-AGV lookup for the optimizer + step-by-step plan streaming (2026-06-13)

Two demo-quality fixes to the chat agent:

- **Optimizer search bound now read live from UE5 instead of hardcoded to 3.** The cell's max
  AGV count was previously frozen at `_DEFAULT_MAX_AGV = 3`, so the optimizer never recognized
  the cell being increased to 5. UE5 `BuildStatusJson` (`/sim/status`) now reports
  `max_agvs = AuthoredAgvs.Num()`; the backend `ProcessTelemetry` carries `max_agvs`;
  `ChatOrchestrator._resolve_max_agv_count` queries it at request time and passes it into
  `parse_optimization_goal(text, max_count)`, falling back to the new `AGV_FLEET_MAX` setting
  (default 5) only when UE5 is unreachable. The planning process for an optimize request now uses a
  deterministic plan (`_OPTIMIZE_PLAN_STEPS`) that includes an explicit "UE5 셀에 배치된 최대 AGV
  대수를 조회" step, so the max-AGV check is visible in the chat.
- **Planning steps stream in step-by-step.** The frontend received all `agent.plan.*` events
  batched in the HTTP response and appended them in one `setItems`, so the whole plan appeared at
  once after it was already finished. `chat-web` now reveals each plan/event item in order with a
  short pause (`PLAN_STEP_REVEAL_MS`), updating the progress indicator per step, and appends the
  assistant reply only after the last step lands.

---

## Agentic AGV-count optimization loop + bottleneck-rate metric (2026-06-13)

Turned the chatbot from a one-shot command dispatcher into a **goal-seeking agent** for the
"find the optimal AGV count" scenario. A request like *"병목률 30% 이하를 만족하는 최적 AGV 대수를
찾아줘"* now drives a closed `observe → judge → decide → re-run` loop that searches AGV
configurations instead of executing one fixed command.

- **New `bottleneck_rate` metric, derived from the congestion heatmap.**
  `domain/process_model.py` is the single source of truth: `bottleneck_rate_from_heatmap()` =
  share of heat-grid cells at ≥60% of peak density (the congested "hot" cells), as a percent —
  the same hot-fraction calculation `evaluation._heatmap_stats` uses and a mirror of the UE5
  `UCongestionHeatmapComponent` density grid. Added to run `kpis`, to single-run
  `build_simulation_evaluation` (lower is better), to A/B `build_run_comparison`, and to the F4
  `acceptance[]` metric enum (`contracts.py` + `router.py`).
- **Deterministic process model.** `process_model.simulate_run_kpis(agv_count)` produces a full
  KPI set (throughput/avg_wait/collision/uptime/heatmap + bottleneck_rate) keyed on AGV count,
  so the agent can evaluate every candidate in-turn without a UE5 round-trip — the demo is fully
  reproducible. Congestion is monotonic in AGV count and calibrated so the 30% goal lands between
  2 and 3 AGVs (n=1≈13%, n=2≈24%, n=3≈39%).
- **The loop.** New `optimize_agvs` route → graph node `optimize_agv_count`.
  `domain/optimization.py` parses the goal (`parse_optimization_goal`) and runs
  `search_optimal_agv_count`, iterating candidates from max(3)→min(1), stopping at the first
  (highest) count that satisfies the goal. `agents/optimization_agent.py` owns the parse+search;
  `_classify_route` gains a deterministic `_is_optimize_request` pre-check (ahead of the LLM, like
  the compare check) so it fires without Ollama.
- **Sub-tasks are real runs.** Each candidate is persisted as a `Simulation` + completed
  `SimulationRun` (with `kpis_json`) and narrated via `agent.optimize.started/iteration/completed`
  + `simulation.created`/`simulation.run.updated` events, so every step shows up in the run
  list/history and the chosen optimum is directly comparable. The loop returns a deterministic
  Korean report listing each tried count and the chosen optimum.
- New tests `tests/test_agv_optimization.py` (10) cover the metric, model monotonicity, goal
  parsing, the search, the route, and the end-to-end loop. Full backend suite: 91 passed (the lone
  error is a pre-existing Windows `%TEMP%` permission issue in `test_llm_benchmark.py`, unrelated).
  Spec: [docs/spec_virtual_process.md](docs/spec_virtual_process.md) "Agentic optimization loop".

## Honest dispatch failure when UE5 is unreachable (2026-06-13)

Fixed a masking bug where a chat-driven simulation/AGV command reported success even when
UE5's AGVSimController (`:7777`) never received it. Previously `Ue5CommandClient.send_robot_command`
swallowed the `httpx.HTTPError` and `RobotCommandOrchestrator.issue_robot_command` then
hard-coded `status = ACCEPTED`, so the chat said "시뮬레이션을 시작합니다 … 실행 ID: …" while the
`/sim/start` POST was actually refused (and `_sync_simulation_lifecycle` still wrote a phantom RUNNING run).

- `send_robot_command` now sets `CommandStatus.FAILED` on `HTTPError` instead of leaving the status untouched.
- `issue_robot_command` respects the returned status (no forced `ACCEPTED`) and emits
  `robot.command.failed` instead of `robot.command.accepted` on failure.
- `_finalize_robot_command` short-circuits on `FAILED`: it skips the lifecycle sync / auto-complete
  (no phantom run, no "실행 ID") and returns a new `_command_dispatch_failed_message` telling the
  operator the simulator wasn't reachable and to confirm the UE5 cell + `:7777` are up.
- `DemoIotCommandClient` (mock mode) still returns `ACCEPTED`, so the demo path is unchanged.
- New test `test_failed_dispatch_is_not_reported_as_accepted`; affected suites pass (orchestrator, ue5_client, chat_api, sim-intent, scenarios).

## Chat UX fixes — start message, pause, run ID, general chat (2026-06-13)

Four chat interaction issues fixed across the backend and frontend:

- **Start message confirms exact settings** — `_clean_accepted_message` for `START_SIMULATION`
  now outputs a multi-line confirmation ("시뮬레이션을 시작합니다.\n- AGV N대 · 속도 Mx배속 · T초\n- 수용
  기준: ...\n- 실행 ID: XXXXXXXX") instead of the bare `command_id=...` fragment.
- **Pause no longer triggers a simulation-complete report** — `handle_completion_event` now
  detects `PAUSE_SIMULATION`, `RESUME_SIMULATION`, and `SET_SIM_SPEED` commands and returns a
  brief acknowledgment message (e.g. "시뮬레이션이 일시정지되었습니다. '재개해줘'로 계속할 수 있습니다.")
  instead of calling `ReportAgent` and emitting `chat.report.generated`. The root cause was that
  the UE5 pause handler sends `robot.command.completed` as an ACK, which the backend previously
  treated identically to a full run completion.
- **Run comparison labels include a unique short ID** — `_run_compare_label` now always appends
  the last 6 chars of `run_id` (e.g. "AGV 3대·1.5배속 (#a1b2c3)"), so repeated runs with
  identical parameters are distinguishable in compare output.
- **Run ID surfaced in the frontend** — when `simulation.created` fires in `logEvent`, the 8-char
  short `run_id` is stored in `currentRunId` state and shown in the `VcoreHud` as "RUN #XXXXXXXX".
  The `simulation.run.updated` terminal states (stopped/completed/failed) clear it back to null.
  The work-log toast for `simulation.created` also shows the short ID.
- **General chat route added** — `general_chat` is now a first-class LangGraph route. The intent
  system prompt gained a `general_chat` intent; `_VALID_INTENTS` and `_VALID_ROUTES` both include
  it. A new `_report_general_chat` graph node calls `_general_chat_message` which fetches recent
  session history (up to 10 messages) and passes it to a new `OllamaLlmGateway.generate_chat_response`
  method for a conversational response with context. `RuleBasedLlmGateway` falls back to a static
  domain-scope message. Conversational queries ("안녕", "아까 뭐라고 했지?", "넌 뭘 할 수 있어?") no
  longer misroute to `station_action_query`.
- **Context and accidental-invocation architecture**: LangGraph thread_id is `{session_id}:{correlation_id}`
  (unique per turn) so no LangGraph state leaks across turns. The tool-execution path always requires
  routing to `robot_command`, and the `_is_explicit_sim_command` guard requires both a sim topic keyword
  AND an explicit lifecycle verb in the current message — so prior "시뮬레이션 시작" messages in history
  cannot re-trigger a command even if the general_chat path passes them as context.
- **64 backend tests pass** (`tests/` excluding path-sensitive benchmark tests).

---

## Chat-driven A/B run comparison (`compare_runs` route) (2026-06-13)

- **New agent intent that compares two simulation strategies.** Asking "방금 결과랑 아까 결과 중에 뭐가
  더 나아?" (or any `비교/compare/대비/어느 게 더/뭐가 더 나아` phrasing) now routes to a dedicated
  `compare_runs` branch in the LangGraph state machine (`report_run_comparison` node). The keyword
  check is deterministic and runs before `classify_intent` — the LLM prompt doesn't know this route
  — but yields to an explicit sim lifecycle command so a stray "비교" inside a start request doesn't
  hijack it.
- **Deterministic A/B verdict on the run history.** `ChatOrchestrator._compare_recent_runs` pulls
  the two newest runs that have final `kpis_json` and feeds them to the new
  `domain.evaluation.build_run_comparison`, which scores each KPI (throughput/avg_wait/collision/
  uptime) on the same higher/lower-is-better directions the single-run grade uses, tallies per-metric
  wins, and — when exactly one run carried acceptance criteria and passed — lets that verdict
  override the tally. Runs are labelled by their sim params (`AGV 5대·1.5배속`), disambiguated by
  recency when identical. Emits an `agent.run.comparison` event for the overlay; needs ≥2 finished
  runs or it asks the operator to run two sims first.
- **Tests:** `build_run_comparison` (metric winner, acceptance override, tie, empty-KPI) in
  `tests/test_scenario_verification.py`; routing + orchestrator integration (`compare_runs` route,
  no-hijack guard, two-run requirement, seeded A/B verdict) in `tests/test_sim_intent_routing.py`.
  Documented in [docs/spec_virtual_process.md](docs/spec_virtual_process.md) and the demo script
  Scenario 8 ([docs/demo_script.md](docs/demo_script.md)).

---

## Offline AGV reset + "Stopped Operation" dashboard state (2026-06-12)

- **Offline AGVs no longer leak previous-run state.** Authored AGVs beyond `AgvCount` used to stay
  frozen in their last-run position/battery — and because the live-telemetry hub keys AGVs by
  `agv_id` and never prunes, the stale unit kept showing in the web AGV list with an outdated
  active state. On sim start, `InitializeRuntimeSimulationActors` now calls the new
  `AAGVActor::ResetToStoppedOperation(InAgvId)` on every authored AGV with index `>= AgvCount`:
  restores the home pose captured at `BeginPlay`, refills battery to 100%, clears
  task/order/load/station fields, drops the recreated traffic/intersection pointers, and parks the
  AGV in the new `EAGVState::StoppedOperation`.
- **All authored AGVs are reported, offline ones shown red.** `EmitTelemetry` now iterates
  `AuthoredAgvs` (active + offline) instead of only `SpawnedAgvs`, so an offline unit emits a fresh
  `STOPPED_OPERATION` frame each cycle (overwriting the stale hub entry) rather than vanishing. The
  web dashboard maps `STOPPED_OPERATION → "가동 정지"` and styles it red (same treatment as
  `STOPPED_COLLISION`) in both the AGV monitor list and the AGV HUD.
- **Offline AGVs are collision-inert.** `OnOverlapBegin` skips an `OtherAgv` in `StoppedOperation`,
  so an active AGV overlapping a parked offline unit never registers a false collision.

---

## Pre-placed AGV actors + collision detection fix (2026-06-12)

- **AGVs are now pre-placed in the level** (no longer spawned at sim start). `AGVSimController`
  gained `AuthoredAgvs` (`EditInstanceOnly` array). On sim start only the first `AgvCount` entries
  are configured and activated; the rest remain offline. On sim stop, AGVs call `StopRun()` and
  stay in the level — they are never destroyed. In the editor, drag the three placed `AGVActor`s
  into the `AuthoredAgvs` slot on the controller (same as `AuthoredPaths`).
- **Collision detection fixed — two-layer approach:**
  1. *Physics layer:* `CollisionComponent` radius raised from 45 → 100 cm; Pawn-to-Pawn collision
     response changed from Block → Overlap so `OnComponentBeginOverlap` now fires between AGVs.
     Previously the Pawn profile blocked other Pawns, so the delegate never triggered.
  2. *Tick-based layer:* `AAGVSimController::CheckAgvProximityCollisions()` runs every Tick when
     the sim is running, checking pairwise 3D distance between all active AGVs. When two AGVs are
     within `CollisionDetectionRadius` (default 300 cm, `EditAnywhere` on the controller),
     `ForceCollisionStop` is called on both. This guarantees detection regardless of frame rate or
     sim speed (`SetActorLocation` without sweep can miss cross-frame collisions at high multipliers).
  `collision_risk` in the KPI report and telemetry now correctly accumulates non-zero when AGVs
  come within the detection radius during a run.

---

## Run-report KPIs & AGV nameplate fixes (2026-06-12) — *awaiting user compile + WBP wiring*

- **Zero-KPI run report fixed.** The end-of-run report (`BuildRuntimeReport`) was showing every
  KPI as `0` (throughput / wait / collision / route-wait / blocked-segments) with uptime stuck at
  `100%`. Uptime-100% + throughput-0 meant AGVs ran continuously but never completed a Load→Unload
  cycle: the P6.1b switch to physics-overlap station detection (`UStationInteractionComponent`)
  wasn't firing at runtime, so AGVs circled in `MovingToPickup` forever. Added a deterministic
  distance-based arrival safety net — `AAGVActor::CheckAutonomousStationArrival` (per tick) queries
  `AAGVSimController::FindNearestStationOfKind` and routes through the state-guarded
  `HandleStationArrival`, so the cell completes tasks (and KPIs become meaningful) regardless of the
  project's Pawn collision-channel responses. The overlap path is retained as the primary trigger.
- **AGV nameplate gained Status + Battery; old status renamed to Task.** `UAGVNameplateWidget`
  now binds `TXT_Task` (renamed from `TXT_Status` — the live activity label), a new `TXT_Status`
  (green "Online" while running / red "Offline" when stopped), and `PB_Battery` (battery 0..1).
  `SetAGVInfo(Name, Task, bOnline, BatteryPercent)`; `AAGVActor` refreshes it each tick so the
  battery bar drains live. New binds are `BindWidgetOptional` so an un-rewired WBP still compiles.
  **Editor work required:** in the nameplate WBP, rename `TXT_Status`→`TXT_Task`, add a new
  `TXT_Status` TextBlock and a `PB_Battery` ProgressBar (see
  [docs/guide_agv_nameplate_widget.md](docs/guide_agv_nameplate_widget.md)).

---

## Phase 1 — Project Scaffold & Integration Skeleton (2026-04-20 ~ 04-21)

### 1.1 Monorepo Structure
- Created monorepo layout: `web/backend/`, `web/frontend/`, `docs/`
- `docker-compose.yml` with PostgreSQL, Redis, FastAPI, React services
- FastAPI project skeleton (`web/backend/`) with DDD folder structure
- React + Vite + TypeScript frontend skeleton (`web/frontend/`)

### 1.2 Database Schema
- Alembic migration 001 with 6 tables:
  - `scenarios`, `simulation_runs`, `kpi_results`, `timeline_logs`, `llm_logs`, `reports`

### 1.3 UE5 Integration Layer
- `AGVSimController` Actor class (C++ header + implementation)
- `POST /api/v1/simulation/start` — creates DB record, triggers UE5 via HTTP
- `POST /internal/ue5/simulation/{run_id}/complete` — writes KPI + timeline rows to DB
- WebSocket relay: `WS /ws/ue5/stream/{run_id}` (UE5 → Redis) + `WS /ws/dashboard/{run_id}` (Redis → browser)
- UE5 HTTP server on `:7777` receives `POST /sim/start`
- UE5 WebSocket client connects to backend stream on sim start
- UE5 HTTP POST to `/internal/ue5/simulation/{run_id}/complete` via `SendSimComplete()`
- Build deps added: `WebSockets`, `HTTP`, `HTTPServer`, `Json`, `JsonUtilities` in `VCORE.Build.cs`

### 1.4 End-to-End Smoke Tests (2026-04-21)
- `POST /simulation/start` → DB record created ✓
- `POST /internal/ue5/complete` → KPI + timeline rows written ✓
- `WS /ws/dashboard/{run_id}` → RunStatus + Redis relay forwarded ✓
- Wrong API key → 403 rejected ✓

### Infra & Stability Fixes (2026-04-21)
- Root `.gitignore` covering UE5 artifacts, Python caches, Node/React artifacts
- Demo run recovery: stale-run cleanup, stop endpoint, UE5 `/sim/stop`, fallback auto-complete
- UE5 WebSocket init stability: `127.0.0.1` loopback, `ws` subprotocol, 3× retry with 2s backoff
- First real UE5 AGV runtime loop: `AGVActor`, `SplinePathComponent`, `IntersectionManager`, `LoadingDockActor`; spawns 3 AGVs, streams real events, computes KPIs
- UE5 game-thread dispatch fix: HTTP-triggered start/stop dispatched to game thread (no off-thread UWorld/timer access)
- Blueprint-configurable AGV spawn/path: `AAGVPathActor` spline references, `AGVActorClass` exposed on controller
- Off-thread crash fix: removed `TWeakObjectPtr<AAGVSimController>` construction from HTTP worker thread
- Off-thread run-state crash fix: HTTP handlers only parse JSON off-thread; all controller state on game thread
- Backend UE5 handoff logging: HTTP status + body logged on `/sim/start`/`/sim/stop` failure
- PIE restart lifecycle fix: routes unbound + state cleared on `EndPlay`; no stale callbacks on restart

---

## Phase 3 — AI Scenario Agent & Real-time Monitoring (2026-04-22 ~ 04-23)

### 3.1 AI Scenario Agent
- `POST /api/v1/agent/chat` streaming SSE endpoint
- LangChain agent with tools: `get_current_kpis`, `propose_scenario`, `start_simulation`
- AGV-domain system prompt for scenario structuring
- Frontend ChatPage: streaming message display, tool-call indicators, "Run Simulation" confirm step
- Fix: navigates to `/simulation/{run_id}` after `start_simulation` tool result; `speed_multiplier` forwarded to UE5

### 3.2 Real-time Monitoring Frontend (2026-04-22)
- `SimulationPage`: run list, start/stop controls, progress bar, event log, KPI gauges wired to WebSocket
- `useSimulationWS` handles `RunStatus`, `RunComplete`, `SIM_PROGRESS` message types
- TanStack Query v5 `refetchInterval` fix; `startMutation.onSuccess` calls `setActiveRun` correctly
- Full demo flow verified: start → monitor → complete → KPI display, stop mid-run

---

## Phase 4 — Comparison View & Approval Workflow (2026-04-23)

### 4.1 Comparison Dashboard
- Backend `GET /api/v1/reports/compare?baseline={id}&modified={id}` — returns KPI delta, creates/reuses report row
- Frontend ComparePage: run selectors, recharts bar chart with per-bar color (green/red), delta summary table

### 4.2 LLM Analysis Report
- Backend `POST /reports/{id}/analyze` — calls Gemini, caches result in `reports.llm_analysis`
- Prompt produces Korean structured JSON: summary, improvements, concerns, recommendation
- Frontend AnalysisPanel renders LLM report sections; "Analyze with AI" button

### 4.3 Approval Workflow
- Backend `GET /reports/{id}` + `POST /reports/{id}/decision` — approve / hold / reject with notes
- Updates `reports.status`, `approved_by`, `approved_at`
- Frontend DecisionPanel (buttons + notes/name fields) + DecisionBadge; decision reloaded from DB on revisit

---

## Phase 5 — PDF Export & Demo Polish (2026-04-23)

### 5.1 PDF Report Generation
- Backend `GET /reports/{id}/pdf` via WeasyPrint; returns bytes directly (no disk storage)
- HTML template: cover page, KPI comparison table, LLM analysis text, decision record
- Dockerfile updated with WeasyPrint system libs
- Frontend "Download PDF" button on ComparePage

### 5.2 Frontend Demo Polish
- Global toast system (`toastStore` + `ToastContainer`) wired to mutation errors
- Loading states, error toasts, empty states for all views
- Modern UI redesign + Korean localization across all pages and AI prompts
- Korean text forced in KPI comparison AI analysis (prompt + tests updated)
- Demo seed data: `web/backend/seed_demo.py` — baseline (68.16 thr, 12.00s wait) vs modified (74.98 thr, 11.40s wait); +10% throughput, −5% wait time exactly
- Backend startup seed fixed: SQLAlchemy `text()` PostgreSQL casts, Korean scenario names restored, `/simulation/runs` alias added, 400 for invalid run UUIDs

---

## Phase 6 — Virtual Process Migration (pai_chatbot) (2026-06-04)

Replaced the entire `web/` stack with the pai_chatbot-derived LangGraph multi-agent system.

### What Changed
- **Backend** (`web/services/chatbot-backend`): DDD/hexagonal FastAPI; chat lifecycle as a LangGraph state machine (`multi_response_graph.py`); LLM via `OllamaLlmGateway`; `Ue5CommandClient` posts commands to UE5 `:7777`
- **Domain rename**: `bed` → `Station`, sensor snapshot → `ProcessTelemetry`
- **Commands added**: `run_station_task`, `move_to_station`, `inspect_station`, `cancel_command`, `start_simulation`, `stop_simulation`, `pause_simulation`, `resume_simulation`, `set_sim_speed`
- **UE5 ingest**: `interfaces/ue5_ingest.py` receives events from UE5; new UE5 routes `/sim/pause`, `/sim/resume`, `/sim/speed`, `/agv/command`, `GET /sim/status` added to `AGVSimController`
- **Frontend** (`web/services/chat-web`): React/Vite WebView overlay (chat + process dashboard) rebranded
- **Control-server-demo**: station registry mock (`/cell/status`, `/stations/{id}`)
- `docker-compose.yml`: `host.docker.internal` wiring, UE5 env vars, `.env.example`
- Backend + control-server tests rewritten for renamed domain
- New spec doc: [docs/spec_virtual_process.md](docs/spec_virtual_process.md)
- CLAUDE.md tech stack section updated

### Sim-intent routing fix (2026-06-08)
A goal-framed run request such as *"AGV를 3대로 시뮬레이션 돌리고, 처리량은 시간당 70 이상,
평균 대기 12초 이하, 충돌 0건이어야 해"* was misrouted to the static process-status report
because `_clean_is_process_status_request` fired on a single KPI noun (`처리량`). Fixed so:
- **Classifier** (`chat_orchestrator.py`): a simulation/command action verb now short-circuits
  the status path; a status read requires a topic **and** a query verb. KPI nouns used as
  acceptance targets no longer hijack the route.
- **Rule-based fallback** (`llm_gateway.py`): `build_rule_based_tool_call` recognizes `돌려/돌리/
  가동/배치/투입/run sim/launch/deploy` as start verbs and parses `acceptance[]` (throughput ≥,
  avg-wait ≤, collisions ==/≤) from the prompt — so AGV deployment **and** the F4 PASS/FAIL
  verdict run end-to-end even when the Ollama tool call comes back empty.
- **Agent plan** (`planning_fallback.py`): a start request now plans analyze → extract KPI goals →
  deploy AGVs → track replay/telemetry → verdict, matching the actual pipeline.
- Tests: `tests/test_sim_intent_routing.py` (+ full suite, 39 passed in Docker).

### LLM-first intent routing (2026-06-08)
Promoted the branch decision from pure keyword matching to an **LLM classifier with keyword
fallback** — the standard agentic-routing pattern — so the agent (not a string compare) assigns
the path:
- `LlmGateway.classify_intent` added (`intent_system`/`intent_user` prompts, JSON `{"intent": ...}`,
  `temperature=0`). `OllamaLlmGateway` implements it; `RuleBasedLlmGateway` returns `None` to defer
  to the keyword net.
- `ChatOrchestrator._classify_route(user_text, correlation_id) -> (route, source)` tries the LLM
  first, validates against `{process_status, station_action_query, robot_command}`, and falls back
  to the keyword classifiers on `None`/invalid/exception. The graph's `classify_request` node calls
  it and publishes an `agent.route.selected` event (`{route, source}`) for observability.
- Verified live (Ollama healthy): "AGV 3대로 시뮬레이션 돌리고 …" → `robot_command` (`source=llm`)
  → `start_simulation` agv_count=3 + 3 acceptance checks; "현재 공정 상태 알려줘" → `process_status`
  (`source=llm`). Full suite 42 passed in Docker.

---

## Phase 7 — Real-time Telemetry, Camera Switching & Multi-AGV Monitoring (2026-06-05)

### UE5 Side
- `AGVActor`: per-AGV chase camera (`UCameraComponent` + boom), battery/destination getters
- `AGVSimController`: UDP telemetry emitter (5 Hz, per-AGV + process), `progress_percent`, `Sockets`/`Networking` build deps
- `AGVSimController`: `POST /camera/select` → `SetViewTargetWithBlend` to AGV camera
- Configurable telemetry transport (`TelemetryTransport=tcp|udp|both|ws`) with TCP JSON-line emitter; `ws` is the default (bypasses Windows Docker-proxy raw-socket black-hole)
- WebSocket telemetry transport: `SendTelemetryWebSocketPayload` streams per-AGV + process frames over the existing backend WS; backend routes `kind=agv|process` frames to `telemetry-collector` via `POST /ingest`
- Centralized `ParseRequestBody` with length-bounded `StringCast<TCHAR>` — fixes intermittent "Invalid JSON" crash from non-null-terminated body reads
- Rebuilt `VCOREEditor Win64 Development` successfully

### `/agv/command` Station Retarget (2026-06-08) — *awaiting user compile*
- `/agv/command` now actually drives a spawned AGV to the resolved station anchor instead of
  only echoing lifecycle events. `AAGVSimController::HandleAgvCommandRequest` picks the target AGV
  (`ResolveCommandAgv`: honors optional `parameters.agv_id`, else first non-collision AGV),
  resolves `station_id` → a deterministic ratio along that AGV's path spline (`StationAnchorRatio`,
  spread within `[0.1, 0.9)`), and calls `AAGVActor::DirectToStation`.
- New `EAGVState::MovingToStation` on `AAGVActor`: moves along the spline to the target distance
  (respecting intersection priority), then returns to `Idle` and calls back
  `AAGVSimController::OnAgvReachedStation`. `robot.moving` is emitted on accept (with `agv_id` +
  `target_station_id`); `robot.command.completed` is deferred until arrival, keyed per-AGV via
  `PendingStationCommands` (cleared on run teardown in `DestroyRuntimeSimulationActors`).
- Drive commands: `move_to_station` / `run_station_task` / `inspect_station`. When no sim is
  running (no AGVs) or the named AGV is unavailable, falls back to emitting `robot.command.completed`
  immediately so the chat turn still closes. `cancel_command` keeps the immediate-complete path.
- Docs: [spec_virtual_process.md](docs/spec_virtual_process.md) endpoint table + follow-ups,
  [test_guide.md](docs/test_guide.md) troubleshooting row.

### Backend
- `POST /unreal/cameras/{agv_id}/select` proxy + `Ue5CommandClient.select_camera`
- `ue5_ingest.py`: routes `kind=agv|process` telemetry frames from UE5 WS to `telemetry-collector /ingest` (container-to-container, no Docker proxy)
- `/ingest` offloads blocking Firebase write to executor — eliminates WS keepalive timeout (was dropping every ~40s) and process-node lag

### Telemetry Collector Service
- New `telemetry-collector` service: asyncio UDP/TCP ingest → Firebase RTDB (`firebase-admin`)
- `POST /ingest` endpoint added for WS-relayed frames
- 7 pytest tests pass in Docker
- Firebase RTDB `cells/cell_demo` writes verified live: `AGV-1/2/3` + `process` nodes

### Frontend (`chat-web`)
- `firebase.ts`: RTDB subscriptions for live telemetry
- Camera switcher: "AGV List" banner → `POST /unreal/cameras/{id}/select`
- Per-camera HUD overlay (battery / status / speed) — shown only when AGV selected
- All-AGV monitor grid
- Live metric cards + progress bar from Firebase
- Top feed: 5s auto-fading work-log toast stack
- ZONE 1 default returns UE5 main camera
- Collision Risk card and Load/Work/Unload workload strip removed
- Pixel Streaming controls repositioned to `top: 60px, left: 270px`
- `tsc -b` + `vite build` pass

### Live SSE telemetry feed + Web HUD migration (2026-06-08)
- **Fixes the stuck "실시간 AGV 텔레메트리를 기다리는 중입니다." empty-state.** The AGV list previously
  depended solely on Firebase RTDB; when the fragile UE→collector→RTDB leg didn't deliver during a
  run, the list stayed empty and the message never cleared. Live data is now Firebase-independent.
- **Backend** `application/live_telemetry.py` (`LiveTelemetryHub`): `ue5_ingest.py` caches every
  `kind:{agv,process}` frame received over the UE5 WebSocket (alongside forwarding to the collector).
  5 s staleness window reports an empty cell once a run stops. `GET /unreal/telemetry/stream` now
  emits `event: agvs`/`process`/`hud` while a sim is live, falling back to `event: telemetry` (IoT
  mock) when idle. Verified end-to-end: WS-injected frames surface on the SSE; the 3 SSE/viewport
  tests in `test_chat_api.py` pass.
- **Web HUD migration:** the in-viewport UE5 HUD (`AVCOREHud` + `UVcoreHudWidget`) was **removed** and
  re-implemented as the `VcoreHud` HTML component (`App.tsx`, top-left of the viewport) — status,
  speed/progress/policy, progress bar, tasks/collisions, verdict badge, recent-events ticker — fed by
  the `hud` SSE frame. `AVirtualProcessGameMode` no longer installs a HUD. HUD fields ride the
  `kind:"process"` frame from `AAGVSimController::EmitTelemetry`. Firebase subscriptions kept as a
  secondary path that only augments (never clears) the SSE feed. `tsc --noEmit` passes; both
  `chatbot-backend` and `chat-web` images rebuilt. **UE5 C++ changes await user compile** (and a
  `p4 reconcile` to mark the 4 deleted HUD files for delete).

### Pixel Streaming 2 Fix
- Vendored UE 5.6 `PixelStreaming2/Resources/WebServers` into `PixelStreaming2WebServers/`
- Ran `npm install` + `npm run build:all:cjs` for local Node packages
- Fixed `LaunchPixelStreaming2Standalone.bat`: call `Scripts\StartPixelStreaming2SignallingServer.bat`, fixed repo-root resolution
- Repointed default `UE5_VIEW_URL` from streamer port `:8888` to player page `:8880`
- Player HTTP 200 on `:8880`, streamer port `:8888` open verified

### Scenario Config, Playback & Run Management
- Backend: scenario CRUD + `/api/v1/scenarios` endpoints (create/read/update/delete/duplicate/run)
- Backend: `/api/v1/runs/{id}/pause|resume|stop|speed|result` REST endpoints proxying UE5
- Postgres/in-memory scenario + run storage; UE completion → run KPI persistence
- Frontend: scenario editor UI + playback / speed controls
- Korean/English command routing tests (22 passed in Docker)

### UX Fixes
- Prevented mouse cursor lock/focus in Unreal viewport iframe (`pointer-events: none`)
- Bypassed "Click to Start" prompt via `AutoConnect=true` query parameter appended to stream URL
- Fixed rule-based tool planning for "Add 1 AGV" chat command
- Conditional iframe/zones/throughput metrics rendering based on active simulation state

### Operator UI Refresh & Session Management (2026-06-07)

**Backend (`chatbot-backend`)**
- New `DELETE /chat/sessions/{session_id}` (204, 404 if unknown): `SessionService.delete_session`
  + `SessionRepository.delete` on both `InMemory` and `Postgres` repos. Postgres clears
  `robot_commands` explicitly (no FK cascade) then the session (`chat_messages` cascades).
- Added `test_session_delete_removes_session_and_history` (create → list → delete → 404);
  `tests/test_chat_api.py` 10 passed in Docker.

**Frontend (`chat-web`)**
- **Chat session list**: redesigned into bordered, compact rows (`.sessionRow`) with an
  open button + trash delete button per session (`deleteSession` API). Deleting the active
  session falls back to the next session or opens a fresh one. Removed the dead hidden
  inline list in the chat dock.
- **Simulation Studio side tab**: the top-left hamburger is now a real toggle button that
  opens a left side tab (`.simSideTab`). The always-on floating scenario panel was moved
  here and rebuilt with a modern sectioned layout: scenario list (per-row delete + "+ 추가"),
  config form, playback/speed controls, and an **실행 기록** run-history list showing past
  run status + KPIs (throughput / wait / speed).
- **Collapsible metric cards**: Process Progress, Uptime (Availability), Avg Wait (Queue
  Delay), Throughput and other left-stack cards each have a `+`/`–` collapse button that
  hides the value body and shrinks the card.
- `tsc -b` + `vite build` pass.

### Viewport Render, Zone Cameras & UI Scrolling (2026-06-08)

**Problem solved:** typing "Run simulation …" in the chat spawned AGVs in UE but the web
viewport stayed blank, the ZONE buttons did nothing, and the session/scenario lists were
hard to scan.

**UE5 (`AGVSimController`) — awaiting user compile**
- `SelectViewTarget` now resolves `zone-1/2/3` (in addition to AGV ids + `overview`) to
  `ACameraActor`s via a new `FindZoneCamera(FName)` helper (`TActorIterator<ACameraActor>`,
  matches actor **Tag** `Zone1`/`Zone2`/`Zone3` or the actor name). `zone-1`/`overview`
  re-enable the F3 auto-director; `zone-2`/`zone-3` call `NotifyManualOverride()`. Added
  `#include "EngineUtils.h"` + `"Camera/CameraActor.h"`. **Editor setup:** tag the three
  Process-level cameras `Zone1`/`Zone2`/`Zone3`.

**Frontend (`chat-web`)**
- **Viewport renders the moment a sim starts.** `isSimActive` now also reflects Firebase
  `process.running` and a new `chatSimActive` flag set on the first sim-driving domain event
  (`robot.command.requested/accepted`, `robot.moving`, `robot.working`), cleared on stop. The
  UE iframe, zone nav, Throughput card and AGV list all appear immediately for chat-driven runs.
- **ZONE 1/2/3 → real cameras.** Zone nav calls `selectAgvCamera("zone-N")` (→ UE
  `/camera/select`) instead of the no-op zone-focus endpoint; `focusUnrealZone` import dropped.
- **AGV list** auto-opens while a run is live and stays open after a selection; each click
  switches the viewport to that AGV's chase camera.
- **Chat session list**: thinner rows; the row title now shows the first user message (not the
  shared prefix) so older sessions are identifiable; scrolls inside the side tab.
- **Simulation Studio split**: left `.simSideTab` shows only the scenario list + run history,
  each independently scrollable; **Configuration** + playback/speed moved to a right-docked
  `.simConfigTab` that opens on scenario select / "+ 추가".
- `tsc -b` passes.

### Chat ↔ Scenario List Unification (2026-06-08)

**Problem solved:** simulations launched from the chatbot drove UE5 directly but never
appeared in the Simulation Studio scenario list — only manually-authored scenarios showed
up. Chat-started and panel-started runs are now unified in one scenario/run store.

**Backend (`chatbot-backend`)**
- `ChatOrchestrator._sync_scenario_lifecycle(command)` mirrors a chat-issued simulation
  lifecycle command into the scenario/run repository, called from the LangGraph
  `finalize_robot_command` node right after `issue_robot_command` (keyed off
  `SIM_LIFECYCLE_COMMANDS`):
  - `start_simulation` → `_create_chat_scenario` builds a `SimulationScenario` from the
    tool-call `parameters` (name `챗봇 시나리오 · AGV {n}대 (MM-DD HH:MM)`) + a running
    `SimulationRun` (`ue_run_id=command_id`); emits `scenario.created`.
  - `stop/pause/resume/set_sim_speed` → `_latest_active_run` resolves the newest active run
    across the repository (so a chat stop also halts a panel-started run) and updates its
    status/speed; emits `scenario.run.updated`.
  - Both events carry `{scenario_id, run_id, status, source:"chat"}` on the chat response +
    the session event WebSocket.
- **Routing guard:** `ChatOrchestrator._classify_route` now overrides an LLM misclassification
  to `robot_command` (`source="llm_guard"`) when the message is an unambiguous sim lifecycle
  phrase (`_is_explicit_sim_command`: a sim topic word + a start/stop/pause/resume verb). This
  fixes Ollama occasionally misrouting "AGV N대로 시뮬레이션 시작해줘" to `station_action_query`,
  which previously dropped the command before it could register a scenario. A bare KPI/status
  question has no lifecycle verb, so it is never pulled into the command path.
- Tests: `test_chat_start_registers_scenario_and_stop_updates_run` (start registers a 4-AGV
  scenario + running run; stop flips it to stopped) +
  `test_explicit_sim_command_overrides_llm_misroute` / `test_guard_does_not_hijack_plain_status_query`.
  Full suite **45 passed** in Docker. Verified live against the rebuilt backend: a UTF-8 chat
  "시뮬레이션 시작" creates a `챗봇 시나리오 · AGV 4대` scenario (list 2→3) + running run; "정지"
  flips that same run to `stopped`. `chatbot-backend` + `chat-web` images rebuilt & restarted.

**Frontend (`chat-web`)**
- The session-event WS handler calls a new non-destructive `reloadScenarioList()` on
  `scenario.created` / `scenario.run.updated` — refreshes the scenario list + selected run
  history without overwriting an in-progress config draft (uses a `selectedScenarioIdRef` so
  the long-lived WS closure reads the live selection). Chat-created scenarios now surface in
  the side tab live and stay manually configurable/runnable from the config panel.
- Added the two events to `loggableEvents` + `eventLabels` (work-log toast) with Korean
  `eventText` and a `scenarioStatusLabels` map. `tsc --noEmit` passes.
- Spec: [docs/spec_virtual_process.md](docs/spec_virtual_process.md) "Chat-driven scenarios
  mirror into the scenario list".

## Phase 8 — Legacy Audit, README Refresh & UE5 Architecture Plan (2026-06-07)

### Legacy Audit
- Swept the repo for content not wired to the running Virtual Process demo and recorded a verdict
  table in [README.md](README.md) ("Legacy / not wired to the current service"):
  - **Remove:** `Source/VCORE/Variant_Strategy/` + `Variant_TwinStick/` (32 TopDown-template files),
    `VCORECharacter.*`/`VCOREPlayerController.*` (after verifying map/GameMode refs), and the stale
    `Source/docs/` mirror (diverged copy of `docs/`).
  - **Keep for history:** deprecated `docs/spec_api.md`, `spec_web.md`, `spec_directory.md` (banners present).
  - **Orphaned:** `web/services/iot-platform-demo` (runs in compose, unconsumed — backend drives UE5 directly).
  - **On-demand tool:** `web/services/data-seeder` (gated behind compose `tools` profile).
  - **Reference only:** `web/docs_pai/`, `web/ARCHITECTURE.md`/`PROPOSAL.md`/`TECKSTACK.md`.

### README Refresh
- Added `telemetry-collector` and `data-seeder` to the services table; corrected the repository-layout
  tree (added `telemetry-collector`, `secrets/`, `docs_pai/`; removed the non-existent
  `NEXT_TASK_PROMPT.md`, pointed to `DONE.md`).
- New "Legacy / not wired to the current service" section + UE-architecture follow-up.

### Legacy Removal — P0 (partial, 2026-06-07)
- Deleted the **Variant_Strategy** template variant in full: `Source/VCORE/Variant_Strategy/` (12 files),
  `Content/Variant_Strategy/` (map, blueprints, materials, anims, UI), and its
  `__ExternalActors__/` + `__ExternalObjects__/` partition data. Removed the matching
  `Variant_Strategy` / `Variant_Strategy/UI` entries from `VCORE.Build.cs` `PublicIncludePaths`.
  Verified no remaining references in `Source/`, `Config/`, the uproject, or `Content/`. Default
  map (`/Game/Warehouse/Scene`) and editor are unaffected.
- Deleted the stale `Source/docs/` mirror (diverged duplicate of `docs/`); `docs/` is now the single
  source of truth.
- **GameMode chain removed (2026-06-07):** reviewed the chain — `GlobalDefaultGameMode` →
  `BP_TopDownGameMode` → C++ `VCOREGameMode` (abstract stub), plus `BP_TopDownController`/`Character`
  over `VCOREPlayerController`/`VCORECharacter`. Confirmed it is pure TopDown-template boilerplate:
  no C++ references it, `AGVActor` is a plain `AActor`, `Variant_TwinStick` inherits engine base
  classes directly, and the digital-twin Warehouse scene (`/Game/Warehouse/Scene`) has no GameMode
  override. Deleted the three C++ class pairs, `Content/TopDown/` (blueprints, cursor FX, input
  actions, template maps) and its `__ExternalActors__/__ExternalObjects__` data. Config cleanup:
  `GlobalDefaultGameMode` → `/Script/Engine.GameModeBase` (neutral until the Virtual Process GameMode
  is authored), removed the 3 dead `ActiveClassRedirects` and the `[/Script/VCORE.VCORECharacter]`
  section, repointed `SimpleMapName` to the Warehouse scene, and set `ProjectName=VCORE`.
  **Compile note:** superseded by the 2026-06-09 successful `VCOREEditor Win64 Development` build.
- **Phase 8 P0 completed (2026-06-09):** verified the `Variant_TwinStick` source and
  `Content/Variant_TwinStick` roots were already absent, then removed the remaining `LVL_TwinStick`
  external actor/object folders and the empty `Content/TopDown/` shell. `AVirtualProcessGameMode`
  already exists under `Source/VCORE/Public|Private/Core`; `GlobalDefaultGameMode` now points to
  `/Script/VCORE.VirtualProcessGameMode`, and the editor's default selected content path no longer
  targets deleted TopDown content.
- **UE compile gate cleared (2026-06-09):** `VCOREEditor Win64 Development` build succeeded with UE 5.7
  after the GameMode repoint and legacy content cleanup.
- **Backend WebSocket fan-out covered (2026-06-09):** added a regression test with two
  `/chat/sessions/{session_id}/events` clients subscribed to the same session while a UE5 progress event
  enters through `/internal/ue5/events`; both clients receive the broadcast. Backend suite: 47 passed.
- **Phase 8 P2 completed (2026-06-09):** extracted `UKPIAccumulator` as a UObject under
  `Source/VCORE/Public|Private/Component`. It now owns task/collision counters and derives runtime
  throughput, average wait, collision risk, uptime, status-frame KPI fields, and scenario-verification
  snapshots. `AGVSimController` now delegates KPI math to the accumulator while keeping event/report
  orchestration. `VCOREEditor Win64 Development` build succeeded after the extraction.

### UE5 Architecture & Directory Partitioning Plan
- New planning doc [docs/spec_unreal_architecture.md](docs/spec_unreal_architecture.md): documents the
  current single-folder, template-derived layout and its God-Class problem (`AGVSimController` =
  1622 lines owning config + HTTP server + WS + 3 telemetry transports + sim lifecycle + KPI + chat
  ingest + camera).
- Defines a **Net / Application / Domain** layering (dependencies inward only; domain has zero network
  includes) and a feature-partitioned target tree (`Core/`, `Simulation/{Agents,Infrastructure}`,
  `Metrics/`, `Net/{Telemetry}`, `Camera/`).
- Responsibility split: extract `USimNetworkComponent`, `USimEventDispatcher`, `UTelemetryEmitter`,
  `UKPIAccumulator`, `UCameraDirector`, `FSimJson` from the controller.
- Phased migration P0–P4 (each independently compilable; demo stays green), risk table, and acceptance
  checklist. Tracked as **Phase 8** in [PLAN.md](PLAN.md).

### UE5 Doc Integration + Portfolio Feature Scaffolding (2026-06-07)

**Design-doc integration**
- Merged the two UE5 specs into a single canonical [docs/spec_unreal.md](docs/spec_unreal.md): the
  runtime/behaviour spec (Parts 1–10) plus the architecture & directory-partitioning plan folded in as
  **Part 11** (previously the separate `spec_unreal_architecture.md`). Added a Part Index + Part 12
  pointer to the new portfolio-feature spec.
- Converted `docs/spec_unreal_architecture.md` to a redirect stub (kept so existing links resolve;
  consistent with the repo's deprecated-doc-with-banner pattern). Repointed PLAN.md Phase 8 to
  `spec_unreal.md` Part 11.

**Portfolio feature design**
- New [docs/spec_portfolio_features.md](docs/spec_portfolio_features.md): four UE5 features chosen to
  showcase the portfolio competencies (real-time data-driven visualization, 3D graphics/rendering,
  AI-agent scenario design & verification) on top of the AGV digital twin, each with an interaction
  scenario and a composed showcase loop.

**Scaffolded C++ classes (engine-only, no asset hard-deps; `public/` header + `private/` cpp)**
- `visualization/CongestionHeatmapComponent` (F1) — decaying density grid from live AGV positions;
  pushes peak density + hotspot into an optional MaterialParameterCollection and exposes
  `GetNormalizedDensityAt` / `GetHottestCell` queries.
- `visualization/AGVStatusBillboardComponent` (F2) — camera-facing `UTextRenderComponent` label
  driven by the AGV's getters; colour-coded by state.
- `cinematics/CinematicEventDirector` (F3) — `FocusOnEvent` cuts/blends a managed `ACameraActor` to
  collision/bottleneck hotspots with severity priority + dwell-return.
- `scenario/ScenarioVerificationComponent` (F4) — evaluates agent-supplied `FScenarioCheck`
  acceptance criteria against an `FProcessKpiSnapshot`, returns a PASS/FAIL `FScenarioVerdict`.
- Classes are not yet wired into `AGVSimController` (kept the buildable controller untouched); wiring
  is tracked as **Phase 9** in [PLAN.md](PLAN.md). **Editor compile confirmed (2026-06-07).**

**Phase 9 wiring — F2 + F3 (2026-06-07)**
- **F2 Status billboards:** `AAGVActor` constructor now creates + attaches a
  `UAGVStatusBillboardComponent` (auto-tracks its owner via the component's BeginPlay), so every
  spawned AGV floats a live, colour-coded `state · battery% · speed` label.
- **F3 Cinematic director:** `AAGVSimController` owns a `UCinematicEventDirector` default subobject;
  `BeginPlay` sets the controller (cell overview) as the return target. `NotifyCollision` cuts the
  camera to the collision position; `EmitBottleneckEvent` resolves the bottlenecked AGV's location
  and cuts there. `SelectViewTarget` now calls `NotifyManualOverride()` on a specific-AGV pick and
  `SetEnabled(true)` on "overview", so manual selection suspends auto-direction until overview is
  reselected. Remaining (Phase 9): tune blend/dwell/severity in PIE; F1 needs the heatmap material;
  F4 needs the backend `acceptance[]` plumbing.

**Phase 9 wiring — F1 + F5 + widget review (2026-06-07)**
- **F1 Congestion heatmap:** `AAGVSimController` owns a `UCongestionHeatmapComponent` default
  subobject; `InitializeRuntimeSimulationActors` registers every spawned AGV and sets the floor rect
  (centered on the controller, `HeatmapFloorSize`, default 4000×4000); `DestroyRuntimeSimulationActors`
  clears it. The density grid + `GetHottestCell`/`GetNormalizedDensityAt` queries work without any
  asset; rendering the floor heat still needs an authored `MPC_Congestion` + `M_FloorHeat` decal.
- **UE5 widget review** (recorded in [docs/spec_unreal.md](docs/spec_unreal.md) Part 7): concluded the
  web overlay keeps the interactive 2D dashboard/controls; UE5 owns only (1) 3D-anchored UI (F2 labels)
  and (2) stream-baked screen UI. No `WBP_*` UMG assets are needed — the old planned
  `WBP_AGVStatusBar`/`WBP_SimMetaPanel` are replaced by F2 (world labels) + F5 (HUD).
- **F5 In-viewport HUD:** new `AVCOREHud` (`core/`) draws — via the engine Canvas, no UMG asset — a
  sim status line, speed/progress/policy, task/collision counters, and a recent-events ticker; it
  renders into the viewport and therefore the Pixel Stream. Reads `AAGVSimController::GetHudSnapshot()`
  (added, plus a 5-entry `RecentHudEvents` ring buffer fed by collision/bottleneck emitters). Installed
  by new `AVirtualProcessGameMode` (`HUDClass`), which also satisfies Phase 8 P0 "author the Virtual
  Process GameMode". **Activation gated:** user must set the GameMode as the map override (left unset
  to avoid an untestable global config flip). `public/core` registered in `VCORE.Build.cs`.

**Module repartition (Phase 8 P1, 2026-06-07)**
- Adopted convention: keep Unreal `public/` (headers) + `private/` (cpp), partition both into
  **purpose subdirectories**. Moved existing classes: `controller/` (AGVSimController), `actor/`
  (AGVActor, AGVPathActor, IntersectionManager, LoadingDockActor), `component/` (SplinePathComponent);
  new features into `visualization/`, `cinematics/`, `scenario/`.
- Registered all `public/*` subdirs in `VCORE.Build.cs` `PublicIncludePaths` so bare-name includes
  (`#include "AGVActor.h"`) keep resolving regardless of `bLegacyPublicIncludePaths`. No source
  `#include` lines needed changing. **Editor compile confirmed (2026-06-07).**

**Phase 9 — F4 Scenario Verification + production UMG HUD (2026-06-07)**
- **F4 end-to-end (AI-agent scenario verification).** The agent can now attach machine-checkable
  acceptance criteria to a run and get a PASS/FAIL verdict back in chat:
  - *Backend:* `START_SIMULATION` tool contract gains an optional `acceptance[]`
    (`metric`/`comparator`/`threshold`/`label`); `ToolRouter._normalize_acceptance` validates entries,
    drops malformed ones, and auto-fills labels. The array passes untouched through `parameters` to
    UE5 `POST /sim/start`. Metrics: `throughput`, `avg_wait_sec`, `collision_count`, `uptime_ratio`,
    `active_agvs`; comparators `>=`/`<=`/`==`.
  - *Engine:* `AAGVSimController` owns a `UScenarioVerificationComponent` default subobject. A file-local
    parser turns the JSON `acceptance` array into `FScenarioCheck`s (`LoadChecks`) at run start;
    `BuildRuntimeReport` builds a `FProcessKpiSnapshot` from the final KPIs, calls `Evaluate`, and
    serializes a `verdict` object (`passed`, `checks_total`, `passed_labels`, `failed_labels`) into the
    report. `SendSimComplete` forwards `verdict` on the `robot.command.completed` payload and retains a
    short verdict line for the HUD; checks clear on run reset/teardown.
  - *Chat read-back:* `_compact_event_context` now forwards `verdict` + `kpis` to the report LLM;
    `report_system.txt` instructs a 합격/불합격 summary; both rule-based fallbacks append a one-line
    verdict via `format_verdict_summary` (new domain helper). Unit tests:
    `tests/test_scenario_verification.py` (6, all pass locally).
- **F5 HUD → UMG widget.** Replaced the Canvas/text-render HUD with `UVcoreHudWidget` (`core/`), a
  `UUserWidget` that builds its tree programmatically in `RebuildWidget`/`BuildLayout` (CanvasPanel →
  Border panel → VerticalBox of status/meta/progress-bar/counters/verdict-badge/event-ticker), so it
  needs **no WBP asset** and still bakes into the Pixel Stream. `AVCOREHud` was rewritten to create the
  widget, `AddToViewport`, and push `GetHudSnapshot()` on a ~15 Hz timer (was per-frame Canvas drawing).
  The snapshot gained `VerdictSummary`/`bVerdictPassed`; the HUD shows a green PASS / red FAIL badge.
  `VCORE.Build.cs` gained `SlateCore`.
- **Editor hand-off.** Wrote [docs/guide_unreal_editor_f4_hud.md](docs/guide_unreal_editor_f4_hud.md):
  compile steps, GameMode activation (HUD), F4 end-to-end verification (incl. a `curl` to prove the pipe
  if the local LLM omits the optional field), optional WBP restyle + F1 material notes, troubleshooting.
  **Pending on the user:** UE C++ compile + set `AVirtualProcessGameMode` as the map's GameMode Override.

### Simulation-start crash fix + overlay/PS layout cleanup (2026-06-08)
- **`StatusBillboard` attachment ensure fixed.** `UAGVStatusBillboardComponent` created its child
  `StatusLabel` (`UTextRenderComponent`) via `CreateDefaultSubobject` in its constructor. On a Blueprint
  subclass (`BP_AGVActor`) the nested default subobject crossed the CDO-template / instance attachment,
  tripping `SceneComponent.cpp:2377` ("Template Mismatch during attachment … Parent 'StatusBillboard'
  (Owner 'Default__BP_AGVActor_C') Self 'StatusLabel'") on every run, stalling the stream ("gave up
  waiting for…"). The label is now created at runtime in `BeginPlay` (`NewObject` + `RegisterComponent`),
  guarded against re-creation. **Pending on the user:** UE C++ recompile.
- **Overlay layout (`chat-web`).** Removed the bottom "⌘ 진행현황 다이어그램" (`diagramButton`) and the
  bottom-right "UE5 View" (`viewportStatus`) boxes — and their dead CSS + the now-unused `firebaseEnabled`
  import. Moved the "AGV 목록 · AGV List" toggle (`monitorToggle`) from top-right to bottom-right
  (`bottom:16px; right:500px`). `npm run build` passes; `dist` regenerated.
- **Pixel Streaming controls relocated.** The player's `#controls` bar (fullscreen / settings / stats)
  was hardcoded to `top:60px; left:270px` — directly under our "VCORE VIRTUAL PROCESS" HUD box. Moved it
  to bottom-left (`bottom:16px; left:16px`) in the served bundle (`SignallingWebServer/www/player.js`)
  and the frontend sources (`ui-library` cjs dist + `src/Styles/PixelStreamingApplicationStyles.ts`) so a
  rebuild preserves it. Served bundle patched directly → no PS rebuild required.

### Process Progress removal + viewport trigger fix (2026-06-08)

- **Process Progress box removed.** The `ProgressRateBar` component (공정 진행률) was
  rendered unconditionally in the left-stack panel and duplicated the simulation progress
  already shown by the `VcoreHud` once a sim is live. The component, its state
  (`isProgressCollapsed`, `progressPercent`), and all associated CSS rules
  (`.progressRate`, `.progressRateHead*`, `.progressRateTrack*`) have been deleted.
- **Viewport render fix.** Added `"scenario.created"` to `simActiveEvents`. The
  `robot.command.requested` / `robot.command.accepted` events are published to the
  InMemoryEventBus (session WebSocket only) and are **not** included in the HTTP
  response `events` array. `scenario.created` IS in that array (via
  `_sync_scenario_lifecycle`). Without this addition the viewport failed to mount when
  the WS delivery of `robot.command.*` raced the HTTP response — the most common case
  when the Ollama model responds in a few seconds. `npm run build` passes; `dist`
  regenerated.

### UE5 WebSocket stream repointed + regression test (2026-06-09)
- Closed the Phase 6 vestigial-stream follow-up: UE5 no longer targets the removed
  `WS /ws/ue5/stream/{run_id}` route. `AGVSimController::ConnectWebSocket` connects to
  `WS /internal/ue5/stream`, and `TelemetryTransport=ws` reuses that backend socket for
  AGV/process/HUD frames. The backend classifies telemetry frames by `kind=agv|process`,
  caches them in `LiveTelemetryHub`, and replays them over `/unreal/telemetry/stream`.
- Added `test_ue5_internal_stream_ingests_live_telemetry`, which opens the authenticated
  internal UE5 WebSocket, sends an AGV frame plus a process/HUD frame, then verifies the
  SSE live feed emits `agvs`, `process`, and `hud` events from those frames.

### Compose default stack cleanup (2026-06-09)
- Moved `iot-platform-demo` behind a Docker Compose `legacy` profile so the default
  Virtual Process stack no longer builds or starts the orphaned IoT mock. It remains
  available on demand with `docker compose --profile legacy up iot-platform-demo`.
- Updated README/spec tracking to describe `iot-platform-demo` as `legacy` profile only;
  `data-seeder` remains a `tools` profile service. The stale `Source/docs/` mirror was
  already removed in the earlier legacy cleanup.

### chat-web dashboard visual confirmation (2026-06-09)
- Verified `http://127.0.0.1:5199` with system Chrome via Playwright. The dashboard
  rendered nonblank with zone controls, KPI metric cards, the AGV list empty-state, and
  the existing chat/session history. Captured evidence at
  `Saved/Automation/chat-web-5199-dashboard-2026-06-09.png`; browser console warnings/errors: 0.

### P1 live-loop end-to-end verification — PASS (2026-06-09)
First fully verified Docker + UE run. UE5 launched as a `-game` standalone via
`LaunchPixelStreaming2Standalone.bat` (Warehouse map, Pixel Streaming signalling on `:8888`);
`AGVSimController` bound the HTTP control server on `:7777` (~20s after launch). End-to-end
results:
- **UE `:7777` reachable** in standalone (`BeginPlay → StartHttpServer → StartAllListeners`);
  config aligned (`[AGVSim] APIKey=dev-agv-key` == backend `AGV_API_KEY`, `CellId=cell_demo`,
  `TelemetryTransport=ws`).
- **Sim loop live** — `POST /sim/start` → `running=true`, `active_agvs=3`, progress/uptime/
  throughput advancing. Confirms the 3-AGV cell (spline paths, `INTERSECTION_X`, dropoff/dock).
  Closes the stale Phase 2.1 item.
- **Lifecycle controls** — start / pause (`paused=true`) / resume (`paused=false`) / speed
  (1.5×, 2.0×) / auto-complete-on-100% all verified directly on `:7777`.
- **UE → backend telemetry** — `GET /unreal/telemetry/stream` (SSE) emits live `agvs`
  (per-AGV position/state/battery/destination), `process` (KPIs, `run_id`), and `hud` events,
  all `cell_id: cell_demo` via the `ws` → `LiveTelemetryHub` → SSE path.
- **backend → UE control** — verified from inside the backend container over
  `host.docker.internal:7777` (Python urllib; `curl` absent in image): `set_sim_speed` accepted
  and applied.
- **Full NL chat round-trip** — `POST /chat/messages` "시뮬레이션 속도를 1.5배로 해줘" → LangGraph
  `sim_lifecycle` plan → `set_sim_speed(1.5)` → UE applied (`speed_multiplier=1.5`); a pause
  request produced `status=accepted` + chat-correlated `agent.plan.*` events. Ollama
  `gemma4:e2b` parsed Korean intent correctly.

This closes the P1 critical-path blocker (UE PIE/`:7777` previously unverified). Remaining P1
editor-only wiring (zone camera `Zone1/2/3` tags, GameMode override confirmation) still needs an
in-editor pass — note `GlobalDefaultGameMode` already targets `VirtualProcessGameMode`, and the
controller spawning + sim running in standalone confirms the GameMode is effectively active.

### Async completion report + "scenario"→"simulation" terminology unification (2026-06-09)
- **Async simulation report now renders in chat.** A simulation completes asynchronously
  (UE's duration timer → `CompleteRuntimeRun` → `SendSimComplete` emits `robot.command.completed`
  with KPIs/verdict long after the chat turn that started it). The backend already generated
  the LLM report and emitted `chat.report.generated` over the session WS, but the web client
  dropped it: `shouldAppendEventToTranscript` only passed `unreal.zone.focus.requested`, and the
  synchronous report path rode the HTTP response. The WS handler now renders `chat.report.generated`
  as an assistant message, keyed by `message_id` so it dedupes against the HTTP delivery. This is
  why the post-fix "processing UI vanishes with nothing" symptom is resolved — the final report now
  appears.
- **Terminology unified to Simulation + Run.** A saved AGV-cell config is now a **Simulation**
  (was the overloaded "scenario"), one execution is a **Run**. Renamed across the web frontend
  (`Simulation`/`SimulationRequest` types, `createSimulation`/`listSimulations`/`runSimulation` API,
  `SimulationPanel`, `simulation_id`, Korean 시나리오→시뮬레이션) and backend (domain model
  `SimulationScenario`→`Simulation`, `scenario_id`→`simulation_id` field, `/api/v1/simulations`
  routes, `simulation.created`/`simulation.run.updated` events, repository methods). **DB columns
  preserved**: Postgres `simulation_scenarios` table and `scenario_id` column are unchanged; the
  repository maps the `scenario_id` column to the `simulation_id` domain field (no migration). All
  47 backend tests pass; `/api/v1/simulations` returns 200, old `/scenarios` 404s.

### Overlay reset + Pixel Streaming reconnect fixes (2026-06-09)
Fixed two overlay defects observed after a scenario finished:
- **HUD froze on "RUNNING 25%".** UE5 emits no terminal frame when a run ends — it just
  stops streaming — so the SSE idle branch (`/unreal/telemetry/stream`) went silent and the
  web HUD/AGV list/running flag kept the last live frame. The idle branch now emits explicit
  reset frames (`agvs: []`, `process: {running:false}`, `hud: null`) before the IoT mock
  telemetry, so the overlay returns to idle and `chatSimActive` clears. `updateDashboardFromProcess`
  now guards `uptime` (absent → leave card untouched, not 0%).
- **"DISCONNECTED. CLICK TO RESTART" viewport.** The embedded Pixel Streaming player gave up
  after 3 reconnect attempts. The iframe URL now passes `MaxReconnectAttempts=999` (with
  `AutoConnect=true`) so the player keeps retrying until the UE streamer registers on `:8888`.
  Also corrected `docs/spec_unreal.md` which wrongly documented `UE5_VIEW_URL=...:8888`
  (the streamer WS port) instead of the player page `:8880`.
- **Play button on a black screen (autoplay blocked).** Once the player connected, it showed a
  play button instead of rendering: UE runs with `-AudioMixer`, so the track carries audio and
  the browser blocked autoplay (the frontend's `AutoPlayVideo` default is `true`, but
  `StartVideoMuted` defaults to `false`). The iframe params now force `StartVideoMuted=true` so
  the muted stream autoplays without a user gesture. The four required player flags
  (`AutoConnect`, `AutoPlayVideo`, `StartVideoMuted`, `MaxReconnectAttempts`) were refactored
  into a single `pixelStreamingPlayerParams` map in `App.tsx` applied by
  `withPixelStreamingParams()`, so no future edit can drop a flag and reintroduce a
  manual-interaction overlay. See `docs/troubleshooting/pixel-streaming-disconnected.md`.

### Speed-aware progress + viewport fill + result report card (2026-06-09)
Fixed three frontend/UE defects reported after running a sim at >1× speed:
- **HUD progress bar capped at `100/speed`% then "completed" (e.g. 25% at 4×).**
  `AAGVSimController::ApplySimSpeed` sets *global time dilation* = `SpeedMultiplier`, so the
  timer manager already ticks `speed`× faster, but `RescheduleSimulationCompleteTimer` and
  `StartDemoFallback` also divided the completion delay by speed — double-counting. The dilated
  timer fired at `1/speed` of the simulated target while `SimElapsedSeconds` (real × speed) only
  reached the same fraction, so the run ended at `100/speed`%. Both timers now schedule in
  *simulated* seconds (no `/speed`); they still elapse after the intended wall-clock interval but
  let the HUD reach 100%. (`Source/VCORE/Private/Controller/AGVSimController.cpp`)
- **Zone camera streams letterboxed (black bars on all four sides).** Added
  `MatchViewportRes=true` to `pixelStreamingPlayerParams` in `App.tsx` so UE renders at the
  iframe's exact resolution instead of preserving a mismatched aspect ratio.
- **Post-run report rendered as a plain chat bubble.** The `chat.report.generated` message is
  now tagged `kind: "report"` and rendered via a dedicated `ReportCard` (header, icon, and a
  PASS/REVIEW/RESULT tone badge) with prominent card styling in `styles.css`.
- **Pass/fail + KPI breakdown shown as cards.** `handle_completion_event` now forwards the
  structured `kpis` and `verdict` from the UE5 completion payload into the
  `chat.report.generated` event. The `ReportCard` renders an ACCEPTANCE PASS/FAIL banner, one
  pass/fail chip per acceptance label (`passed_labels`/`failed_labels`), and a per-KPI card grid
  (Throughput, Avg Wait Time, Collision Risk, Uptime) above the LLM narrative — driving the
  header badge from the real verdict when present.

### Skeletal-mesh AGV animation + Studio result cards + AI evaluation (2026-06-10)
Fixed three issues reported after the AGV mesh was swapped to a skeletal mesh:
- **Drive animation never played when the AGV moved.** The AGV moves procedurally via
  `SetActorLocation`/`SetActorRotation` (no movement component), so the engine's default
  `AActor::GetVelocity()` stayed zero and any locomotion AnimBP saw no motion. `AAGVActor` now
  overrides `GetVelocity()` to return `GetActorForwardVector() * CurrentSpeed`, so a standard
  "GetOwningActor → GetVelocity" locomotion graph blends idle↔drive correctly. Also exposed
  `GetCurrentSpeed()`, `IsMoving()`, and `GetStateName()` as `BlueprintPure` for AnimBP wiring.
  **Follow-up (humanoid skeletal mesh):** reparented `AAGVActor` from `AActor` to **`APawn`**
  (lightweight — no `CharacterMovementComponent`; AI/player possession disabled) so a humanoid
  locomotion ABP's `TryGetPawnOwner → GetVelocity` path resolves and reads the override. The
  placeholder `VisualMesh` (engine cube `UStaticMeshComponent`) was removed now that the AGV uses
  a skeletal mesh assigned on the Blueprint. (A short-lived pose-tick/URO workaround was tried and
  reverted — idle/locomotion ticks correctly in PIE without it.)
  (`Source/VCORE/Public/Actor/AGVActor.h`, `Source/VCORE/Private/Actor/AGVActor.cpp`)
- **Result report now also viewable inside Simulation Studio.** Each finished row in the run
  history list is expandable; the same result card shown in chat (verdict banner + chips + KPI
  grid + heatmap + AI evaluation) is reconstructed from the run's persisted `kpis_json`/
  `result_json`. Run rows are status-colored via a left banner: in-progress (starting/running)
  blue, completed light green, paused amber, failed red. (`App.tsx`, `styles.css`)
- **Overall AI evaluation added on completion (beyond the numbers).** New deterministic
  `buildAiEvaluation()` analyzes the heatmap grid (congestion concentration ratio, hot-cell
  fraction, hotspot quadrant) plus each KPI to produce a graded (A/B/C) qualitative assessment
  with a headline and per-metric notes. Rendered as an `AiEvaluationCard` inside both the chat
  `ReportCard` and the Studio result detail. (`App.tsx`, `styles.css`)

### ReportAgent narrative evaluation (2026-06-10)
- **Backend now authors the qualitative narrative.** New `app/domain/evaluation.py`
  `build_simulation_evaluation(kpis, verdict)` mirrors the frontend `buildAiEvaluation` thresholds
  and produces a graded (A/B/C) `SimulationEvaluation` with heatmap analysis (concentration ratio,
  hot-cell fraction, hotspot quadrant) + per-KPI notes. `ReportAgent.generate_report` computes it,
  passes `to_prompt_block()` to the LLM via a new `evaluation` param, and the `report_system`/
  `report_user` prompts instruct the model to weave it into a **separate "AI 종합 평가" narrative
  section** after the result summary. The deterministic `to_narrative()` is appended in the
  rule-based and LLM-error fallbacks so the assessment always appears. `LlmGateway.generate_report`
  (protocol + Ollama + rule-based gateways) gained the optional `evaluation` argument. Covered by a
  new `test_report_agent_fallback_appends_evaluation_narrative` (full suite: 49 passed).
  Apply with `docker compose build chatbot-backend && docker compose up -d chatbot-backend`.

### Report truncation + AGV spawn-collision fixes (2026-06-10)
- **Report no longer clipped mid-sentence.** The LLM report budget `report_num_predict` was 192
  tokens, which cut multi-sentence KPI narratives off (e.g. "…92% uptime is the amount"). Raised to
  **512** in `infrastructure/config.py` (`ollama_report_num_predict` default + `OLLAMA_REPORT_NUM_PREDICT`
  env fallback) and the `OllamaLlmGateway` constructor default. Plan/tool budgets unchanged. No
  character-level slice exists on the output, so the token cap was the sole cause. Apply with
  `docker compose up -d chatbot-backend` (config-only; rebuild not required).
- **AGVActor "failed to spawn due to collision" fixed.** `AGVSimController::EnsureRuntimeActors`
  spawned the intersection/dock/AGVs with a default `FActorSpawnParameters` (collision handling
  `Undefined`), so the engine dropped actors whose start locations overlapped near the controller.
  Set `SpawnCollisionHandlingOverride = AdjustIfPossibleButAlwaysSpawn` so actors always spawn
  (nudged out of penetration when possible). **Requires a UE rebuild / Live Coding pass to take effect.**

### llama.cpp GPU benchmark re-run (2026-06-10)
- **Root cause of the earlier llama.cpp lag found and fixed.** The previous Ollama-vs-llama.cpp
  benchmark (`docs/benchmark/README.md`) showed llama.cpp ~5× slower (~11.7 s avg). The cause was
  not the harness — the `llama-server.exe` in `Intermediate\llama-build` was a **CPU-only build**
  (`GGML_CUDA=OFF`, no `ggml-cuda.dll`, `--list-devices` empty), so `-ngl` had no CUDA backend to
  offload to. Reconfigured with `cmake -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=89` and rebuilt the
  `llama-server` target; `ggml-cuda.dll` now ships and the binary reports `CUDA0: RTX 4060 Ti`.
- **Re-ran the benchmark with full GPU offload (`-ngl 99`).** llama.cpp average latency dropped from
  ~11.73 s to **~2.37 s** (p95 4.37 s, stddev 1.09 s) — now on par with Ollama (~2.01 s) and slightly
  better on tail latency. Tool-selection accuracy 91.67% (vs Ollama 66.67%); Ollama still wins on
  structured-output validity (JSON/schema 91.67%/83.33% vs 58.33%/58.33%). ~2.2 GB VRAM footprint.
- Regenerated `docs/benchmark/raw/llm_provider_comparison.{json,csv}`, captured the GPU server log at
  `docs/benchmark/raw/llama-server-qwen35-2b-gpu.log`, and rewrote `docs/benchmark/README.md` (GPU run
  promoted to the headline tables; CPU-only numbers preserved in an appendix). Focused tests
  `tests/test_llm_benchmark.py tests/test_llm_gateway.py` → 20 passed.

### Benchmark v2 — validation-layer ablation (Phase 2, 2026-06-11)
- **Built the v2 benchmark harness** (`app/benchmarks/cases_v2.py`,
  `case_generator.py`, `benchmark_v2.py`, `report_v2.py`; runners
  `scripts/generate_v2_cases.py`, `scripts/benchmark_v2.py`). Fixes the Phase-1
  weaknesses: argument-level scoring (`exact`/`subset`/`ignore`, numeric-string
  coercion, nested `acceptance[]` subset matching), Wilson 95% CIs on every rate,
  and a **133-case bilingual suite** (en+ko, ≥10/category) committed as static
  JSONL in `docs/benchmark/cases/v2/`.
- **Added ablation toggles to the gateway** (`OllamaLlmGateway`):
  `enable_rule_based_fallback`, `enable_argument_normalization`, plus
  `structured_retry_count=0`. Layer logic stays byte-identical across providers
  (llama.cpp subclass overrides only `_post_chat`), so the 2×2 (Ollama/llama.cpp ×
  layer off/on) measures the same code on both.
- **Ran the full 2×2** (133 cases × 4 cells × R=5 = 2,660 trials; `qwen3.5:2b` on
  both Ollama and a CUDA llama.cpp serving the same GGUF). Headline Task Success:
  Ollama **75.2%** off → 54.3% on (**−20.9 pp**); llama.cpp 53.5% off → **66.2%**
  on (**+12.6 pp**) — non-overlapping CIs. **The layer helps the weak model and
  hurts the strong one;** raw Ollama (layer off) is the best cell and beats the
  shipped production path.
- **Root-caused** both directions: the repair-retry prompt is *coercive* (forces a
  tool, collapsing Ollama's correct declines on negative/ambiguous/missing from
  ~90% to ~0%), while llama.cpp's gains are carried by the deterministic regex
  fallback (38.6% fire rate), not the model. Surfaced two actionable bugs
  (decline-coercion in the retry; no value-range checks in `ToolRouter.validate`)
  and scoped Phase-3 fine-tuning to the genuinely model-limited categories
  (`kpi_acceptance` ~20%, `multi_parameter`). Full analysis:
  `docs/benchmark/PHASE2_RESULTS.md`; generated tables + raw JSON/CSV in
  `docs/benchmark/raw/phase2_validation_ablation.*`. Tests:
  `tests/test_benchmark_v2.py` → 12 passed.

### Phase 2-B — validation-layer fix verification (2026-06-11)
- **Implemented the two Phase-2-A fixes** (gated to layer-ON cells only, so A1/B1
  stay the Phase-2-A baseline). **Fix 1 (decline support,
  `llm_gateway.propose_tool_call`):** a clean LLM "no-tool" response is now a valid
  terminal decline — it is no longer retried (the coercion bug) nor handed to the
  rule-based fallback (the second-cut bug); the repair prompt is non-coercive with
  an explicit `{"name":"none"}` escape hatch, and only *malformed/out-of-range* tool
  calls trigger retry/fallback. **Fix 2 (range checking, `ToolRouter.validate(...,
  check_ranges=True)`):** station_id ∈ [1,99], 0 < speed ≤ 10, agv_count ∈ [1,50];
  out-of-range values raise `ToolValidationError` and the fallback is range-checked
  too so it can't smuggle them back.
- **Ran a targeted 7-category smoke test** (`docs/benchmark/cases/phase2b_smoke/`,
  70 cases × R=3 × 4 cells = 840 runs). Took 3 iterations to get Fix 1 right
  (archived `raw/phase2b_v1`, `_v2`); the final result **inverts the Phase-2-A
  headline**: layer-ON now beats layer-OFF on both providers — Ollama **62.9% off →
  64.3% on**, llama.cpp 54.3% off → **58.1% on**. Ollama decline categories
  recovered (negative_control **2.9% → 88.1%**, ambiguous 0% → 76.7%,
  missing_parameter 0% → 52.8%); `invalid_parameter` **0% → ~57–60%** on both.
  Retry rate down (26.2% → 16.7%), repair success up (5.7% → 54.3%).
- **Decision: GO** for the full-scale Phase 2-B run; Phase 3 fine-tuning still
  scoped to the model-limited `kpi_acceptance`/`disambiguation`/`multi_parameter`
  semantics. Full writeup: `docs/benchmark/PHASE2B_FIX_VALIDATION.md`; raw tables in
  `docs/benchmark/raw/phase2b/`.
- **Serving caveat:** the re-pulled `qwen3.5:2b` is a reasoning model the pinned
  llama.cpp builds can't load; ran via Ollama's bundled `llama-server --reasoning
  off`. A-cell (Ollama) comparison to Phase 2-A is clean; B-cell magnitude is a
  different regime (llama.cpp now emits valid JSON without the fallback) and is
  directional only.

### Phase 2-B — full-scale run + serving baseline resolved (2026-06-11)
- **Serving baseline resolved as Option A.** The project's *current* CUDA llama.cpp
  build — `llama-server` **9559 (`715b86a36`)**, the one rebuilt with `GGML_CUDA=ON`
  on 2026-06-10 — loads the exact re-pulled GGUF blob (`sha256-b709d815…`) that the
  *pinned* builds couldn't, and runs it `--reasoning off --reasoning-budget 0`. So the
  B cells now run on the **project's own llama.cpp binary** serving the identical blob,
  not Ollama's bundled server — Phase 2-B is internally consistent (one blob, one
  reasoning-off regime). The B-cell magnitude vs Phase 2-A stays directional because the
  *model* was re-pulled to a reasoning variant (reasoning-off llama.cpp is now
  JSON-capable: B1 first-pass schema 24.4% → 86.8%, fallback fire rate 38.6% → 1.5%).
- **Ran the full 133-case × 12-category × R=5 × 4-cell ablation** (2,660 scored cases)
  via host anaconda Python. Hardened the run against the idle-sleep that killed the first
  attempt: non-admin `SetThreadExecutionState` wake lock + unbuffered logging.
- **Results (Task Success, Wilson 95% CI, n=665/cell):** A1 75.6% [72–79], **A2 75.9%
  [73–79]**, B1 69.0% [65–72], **B2 74.0% [71–77]**. The Phase-2-A regression is repaired
  with non-overlapping CIs (**A2 54.3% → 75.9%, +21.6 pp**); the layer is now neutral on
  Ollama (A1≈A2) and a significant +5.0 pp on llama.cpp (B1 vs B2 non-overlapping). Retry
  rate fell to ~8% (was A2 26% / B2 76%), repair success rose (A2 52.5%, B2 60%),
  `invalid_parameter` 8%→56% / 2%→60% (range-check fix), `multi_parameter` now 100% on all
  cells. Latency cost of the layer is now small (~0.1–0.5 s).
- **Decision: Phase 2-B PASS. Phase 3 LoRA SFT = conditional GO (recommend, not started),**
  narrowed to **`kpi_acceptance`** (Ollama 18–22%, nested `acceptance[]` extraction) +
  **`disambiguation`** (Ollama 60%, verb/tool sensitivity); `multi_parameter` drops from
  scope (now solved). Full writeup: `docs/benchmark/PHASE2B_FULL_RESULTS.md`; raw tables in
  `docs/benchmark/raw/phase2b_full/`.

### Phase 2.5 — enriched tool-planning prompt shipped (2026-06-11)
- **Promoted the Phase-2.5 enriched prompt into production.** Copied
  `app/prompts/templates_phase25/tool_planning_system.txt` into the shipped
  `app/prompts/templates/tool_planning_system.txt` (now byte-identical). The enrichment is
  two compact plain-text lines — a verb→tool mapping (go/move→`move_to_station`,
  work/run→`run_station_task`, check/inspect→`inspect_station`) and an `acceptance`-array
  spec for `start_simulation` — deliberately **no** inline JSON exemplars (those collapsed
  the 2B model to 0% in the diagnostic).
- **Confirmed no regression with the full 133-case Phase-2 suite** (Ollama, layer ON = A2,
  R=5, n=665): `kpi_acceptance` **22.0→94.0%** (CI-separated, the +72 pp win held and
  exceeded the 92% probe), **every other category within CI overlap** of the PHASE2B A2
  baseline, overall task success **75.9→77.1%** (+1.2 pp). Gate (kpi gain holds AND no other
  category regresses beyond CI overlap) **passed → shipped**. A soft, within-CI downward
  drift on the decline categories (negative_control/ambiguous/missing_parameter/
  state_dependent) is logged as a watch-item per the 2B prompt-length-sensitivity caveat.
  Raw: `docs/benchmark/raw/phase25_full_regression/`; addendum in
  `docs/benchmark/PHASE25_DIAGNOSTIC.md`.

### Phase 2.5 — disambiguation serving lever resolved; Phase 3 SFT closed out (2026-06-11)
- **Re-measured the sole surviving residual (`disambiguation`) on the project llama.cpp 9559
  binary reasoning-off** — the last open action from the diagnostic. Launched
  `Intermediate/llama-build/bin/Release/llama-server.exe` v9559 (`715b86a36`) serving the identical
  Phase-2-B GGUF blob `sha256-b709d815…` on `:8080` (`-ngl 99 -c 8192 --jinja --reasoning off`),
  ran `scripts/phase25_diagnostic.py --providers llama_cpp --repeats 5` (layer ON = A2/B2).
- **Result: `disambiguation` 91.7% [81.9–96.4]** (55/60) — exceeded the Phase-2-B ~80% prediction
  and beat the same blob on Ollama by **+28 pp** (Ollama enriched 63.3%); `kpi_acceptance` 100%
  (50/50). Pure serving-regime effect (shipped prompt == `templates_phase25` since the morning ship).
  Residual is a single rare prototype (`"Work station 3."` → `inspect_station`), now 8.3% vs ~40% on Ollama.
- **Decision: Phase 3 LoRA SFT closed out as unnecessary.** Both former Phase-3 targets are now
  carried by free levers (prompt for `kpi_acceptance`, serving for `disambiguation`). Recommended
  production path: llama.cpp 9559 reasoning-off + the shipped enriched prompt. Raw:
  `docs/benchmark/raw/phase25_llamacpp/`; writeup appended to `docs/benchmark/PHASE25_DIAGNOSTIC.md`.

### Known Constraints (as of 2026-06-09)
- **UE C++ change above needs an editor rebuild** to take effect (no build run on this host per the deferred-UE-build workflow). The frontend changes are live after a `chat-web` rebuild/HMR.
- UE5 raw-socket UDP and TCP to Dockerized collector both fail on this Windows host — Docker Desktop's proxy drops bytes silently. Telemetry default is `ws` transport.
- KPI compare / LLM report / approval / PDF from old web stack not yet rebuilt for Virtual Process

---

## Phase 3 — LLM SFT: Domain Tool Routing (2026-06-11)

### SFT-1 — Dataset creation (complete)
Built a 450-row tool-routing SFT dataset (Train 300 / Val 50 / Test 100) to internalize
V-CORE domain tool routing into a LoRA-tuned Qwen 2B-class model, so accurate
`{"name","arguments"}` control JSON is produced under a *minimal* prompt. Framed as a
**portfolio capability** demo (reduced long-prompt dependence), not an ops-perf fix —
production already sits at 94% KPI acceptance / 91.7% disambiguation.

- Generator `docs/sft/scripts/build_sft_dataset.py` extends the 133-case v2 benchmark via
  template + slot expansion (verb / station-form / courtesy-suffix / named-area aliases,
  ko+en). Labels are **grounded on the 9 real production tools** in `tools/contracts.py`
  (not the brief's illustrative `assign_transport_order`/`move_agv` names); decline rows use
  the gateway's production sentinels (`none` / `clarify`).
- `docs/sft/scripts/validate_labels.py` confirms **450/450 labels valid** against the live
  `ToolRouter.validate(check_ranges=True)`. Build asserts zero prompt overlap across splits
  (450 unique) and exact per-category counts; over-weights the two Phase-3 SFT targets
  (`disambiguation` 90, `kpi_acceptance` 81).
- Deliverables in `docs/sft/data/`: `train/val/test.jsonl`, `alias_map.json`,
  `dataset_card.md`, `lora_config.yaml` (SFT-2 config staged). Plan + checklist:
  `docs/sft/plan.md`; result writeup: `docs/sft/RESULT_SFT1.md`.
- SFT-3 eval harness `docs/sft/scripts/eval_sft.py` is staged to grade the {Base+Full,
  Base+Minimal, SFT+Minimal} matrix over the held-out test set against the fixed Phase-2-B baseline.

### SFT-2 — QLoRA training (complete)
LoRA fine-tuned the production base `Qwen/Qwen3.5-2B` (= Ollama `qwen3.5:2b`) on the 300-row
train split so V-CORE tool routing is internalized under the *minimal* prompt. **Base weights
untouched** — only a separate adapter + a merged copy are produced.

- Training script `docs/sft/scripts/train_lora.py`: QLoRA (4-bit NF4, r=16/α=32 on
  q,k,v,o,gate,up,down_proj), minimal prompt as system, **completion-only loss** (prompt tokens
  masked). 3 epochs / ~6.8 min on host RTX 4060 Ti; eval_loss 0.0315 → 0.0037 → **0.0029**.
- Ran on a **dedicated venv** `C:/Users/PC/sft-train-venv` (torch 2.6.0+cu124, transformers
  5.11, peft 0.19.1, bitsandbytes 0.49.2) so the benchmark anaconda env's CPU torch is untouched.
- Artifacts in `docs/sft/data/`: adapter (`adapter/`, 43 MB / 10.9 M params), merged fp16
  (`merged-fp16/`, 3.76 GB), and **GGUF q4_k_m** (`vcore-toolrouter.gguf`, 1.27 GB) that loads
  on the pinned llama.cpp `:8080` for SFT-3 serving parity. Smoke test: **6/6** held-out prompts
  routed correctly (ko+en) under the minimal prompt. Writeup: `docs/sft/RESULT_SFT2.md`.
- Non-obvious fixes (Windows / py3.13 / new `qwen35` arch): `import datasets` before `torch`
  (pyarrow×torch DLL load-order segfault); GGUF convert needed `dt_bias`→`ssm_dt` naming +
  `--no-mtp` (block_count 25→24) to match the loader; built the missing `llama-quantize` target.

### SFT-3 — Held-out evaluation (complete) — **PASS**
3-way matrix over the 100-row held-out `test.jsonl`, one scorer (`scripts/eval_sft.py`), all
conditions served on the same llama.cpp `:8080` for parity:

| Condition | Task Success |
|---|---:|
| Base + Full prompt | 49 % |
| Base + Minimal prompt | 12 % |
| **SFT + Minimal prompt** | **96 %** |

The SFT model under the 4-line minimal prompt (96 %) **~2×** the base under the full production
prompt (49 %) and **8×** the base under the minimal prompt (12 %) — proving V-CORE tool routing
is internalized in the weights rather than carried by the long hand-tuned prompt. SFT-target
categories: disambiguation 30→**95 %**, kpi_acceptance 50→**100 %**; decline discipline
(invalid/missing param) 0→**100 %**. All three success gates pass (only `run_station_task`
100→90 % dips vs Base+Full, not a gate metric). Full table + analysis: `docs/sft/RESULT_SFT3.md`.
This closes Phase 3 SFT (SFT-1 data, SFT-2 training, SFT-3 eval all complete).

### SFT-4 — Deploy the router into the backend (routing-only split) (2026-06-15)
The SFT model existed only in the eval harness; the live backend still ran base `qwen3.5:0.8b`
on **every** LLM call, so production tool routing picked the wrong tool (e.g. "5 AGVs at 1x" →
`set_sim_speed` instead of `start_simulation`). Deployed the SFT GGUF behind the LLM boundary
**for tool routing only**, since SFT trained `propose_tool_call` exclusively (chat / intent /
plan / report were untrained and would regress on a JSON-tuned model):

- New `LLM_PROVIDER=routing_split` → `RoutingSplitLlmGateway` (`infrastructure/llm_gateway.py`):
  delegates `propose_tool_call` to a llama.cpp gateway serving `docs/sft/data/vcore-toolrouter.gguf`
  on `:8080`, and `classify_intent`/`generate_plan_steps`/`generate_chat_response`/`generate_report`
  to Ollama. General model bumped `0.8b → qwen3.5:2b` (benchmarked production model).
- The router is prompted **exactly as trained**: minimal system prompt
  (`prompts/templates/tool_planning_system_min.txt`, mirrors `eval_sft.py`'s `MINIMAL_PROMPT`),
  **bare user command** (no `tool_planning_user` wrapper / station context), no tool schema in
  the payload — added `tool_system_template` / `tool_user_template` / `send_tool_schema` knobs to
  `OllamaLlmGateway`. `enable_decline_retry` on so the model's `clarify`/`none` outputs resolve to
  a clean no-tool (already in `_DECLINE_NAMES`).
- **Boundary aliases** (`_TOOL_NAME_ALIASES`/`_ARG_KEY_ALIASES`): the SFT model emits
  `run_simulation`→`start_simulation` and `agv_speed_multiplier`→`speed_multiplier` on the
  *compound* "start + speed" case — a pairing with **zero** coverage in the training labels (all 11
  `speed_multiplier` labels are on `set_sim_speed`; start+speed never co-occur). Aliases remap them
  to the contract so the call validates. **Proper fix deferred: add compound start+speed rows to the
  SFT dataset and retrain** — see `docs/sft/plan.md`. ✅ **Done in SFT-5 (below); aliases removed.**
- Verified live against `:8080` through the real gateway code (`propose_tool_call`+`validate`):
  "5 AGVs at 1x"/"5대 1배속"→`start_simulation{agv_count:5,speed_multiplier:1.0}`; "2배속 4대로
  시작"→`{agv_count:4,speed_multiplier:2.0}`; "속도 2배"→`set_sim_speed{2.0}`; station 999 / "what
  can you do" → clean decline. Backend `/llm/status` reports
  `vcore-toolrouter (routing) + qwen3.5:2b (general)`.
- **Runtime requirement:** `llama-server` must serve the SFT GGUF on `:8080` (host), reachable from
  the backend container as `host.docker.internal:8080`. Launch:
  `Intermediate/llama-build/bin/Release/llama-server.exe -m docs/sft/data/vcore-toolrouter.gguf
  --host 0.0.0.0 --port 8080 -ngl 99 -c 8192 --jinja --reasoning off --reasoning-budget 0`
  (note: `--no-mtp` is **not** a valid serving flag for build 9559).

### SFT-5 — Close the start+speed gap in the data, retrain, remove the aliases (2026-06-15)
Replaced the SFT-4 boundary aliases with the proper fix — the routing was put into the weights:

- **Dataset (`docs/sft/scripts/build_sft_dataset.py`, 495→531 rows).** Two new categories appended
  *last* so every prior category draws an identical seeded sequence (existing splits unperturbed,
  verified by exact per-category counts):
  - `start_with_speed` (30/5/10): `start_simulation` carrying **both** `agv_count` and
    `speed_multiplier` (1x/1.5x/2x/3x, EN+KO, ~25% also with `acceptance[]`) — the pairing that was
    missing (all 11 original `speed_multiplier` labels were on `set_sim_speed`).
  - `kpi_acceptance_metrics` (24/4/8): `start_simulation` + `acceptance[]` on the previously
    **zero-coverage** metrics `bottleneck_rate` (percent 0–100, matches the heatmap KPI),
    `uptime_ratio` (0–1), `active_agvs` (count). Phrased as *single-run verifiable* goals with no
    optimize verb, so they don't collide with the upstream optimizer (`is_optimize_request`); a
    self-check confirms 0/531 of the new rows would be hijacked by it. All 531 labels re-validated
    against the live `ToolRouter`.
- **Retrain.** Same QLoRA config (r16/α32, 3 epochs); 69 steps / ~7.3 min; eval_loss 0.0209→0.0033.
  Fixed a *new* env blocker: the venv's `pandas` was upgraded to 3.x, which calls
  `platform.win32_ver()` (a WMI probe) at import — on this host WMI now hangs, so `import datasets`
  (and thus the whole trainer) hung silently with no output. `train_lora.py` now neutralizes the WMI
  probe before importing datasets (falls back to the registry path).
- **Quantization finding (the real catch).** Adapter, merged-fp16, **and the f16 GGUF** all emit the
  correct `speed_multiplier`/`bottleneck_rate`, but **q4_k_m washed the new (smaller, 30-row)
  distinctions out** — the q4 model reverted to its base prior (`agv_speed_multiplier`,
  `run_simulation`) and scored `start_with_speed` **0/10**. **q5_k_m preserves them** at +0.07 GB
  (1.34 GB). The deployed `docs/sft/data/vcore-toolrouter.gguf` is now q5_k_m; `lora_config.yaml`
  `quantize` updated q4_k_m→q5_k_m.
- **Eval (SFT+Minimal, held-out 118 rows, q5_k_m on :8080): 98.3% (116/118).** `start_with_speed`
  10/10, `kpi_acceptance_metrics` 8/8, `kpi_acceptance` 18/18, disambiguation 20/20 — no regression
  (2 minor misses in move/sim_lifecycle, on par with the prior 96% run).
- **Aliases removed.** Deleted `_TOOL_NAME_ALIASES`/`_ARG_KEY_ALIASES`, `_apply_aliases`, and their
  application in `_tool_call_from_parts`/`_extract_tool_call` (`infrastructure/llm_gateway.py`).
  End-to-end through the real routing gateway (`propose_tool_call`+`validate`, range-validation on,
  no aliases) now yields natively: "1x with 5 AGVs"/"2배속 4대로 시작"→`start_simulation{agv_count,
  speed_multiplier}`; bottleneck/uptime/active_agvs acceptance correct; "속도 2배"→`set_sim_speed`
  (not hijacked); station 999 / "what can you do" → clean decline.
- **Note on optimization search.** "Find the *optimal* AGV count under a bottleneck %" was confirmed
  to already exist as a dedicated keyword-routed node (`is_optimize_request`→`optimize_agv_count`,
  `domain/optimization.py`), upstream of and separate from the tool router — out of scope for the SFT
  router by design. The new acceptance-metric rows cover only the single-run verifiable case.

---

## StateTree AGV — "AGV does not move on start" fix + PIE test harness (2026-06-12)

### Root cause
The StateTree migration hard-gates **all** AGV movement on `UStateTreeComponent::IsRunning()`:
`AAGVActor::StartRun` → `UAGVTaskComponent::ResetForRun` returns false unless the StateTree
actually starts (`bRequireStateTreeForControl=true`), so `bRunActive` never goes true; and every
`AAGVActor::TransitionTo` is additionally gated through `CanExecuteControlOperation`. The cell
froze because the controller's spawn path (`AGVActorClass`, default `AAGVActor::StaticClass()`)
was spawning the raw C++ class with no StateTree assigned — `StartLogic()` → not running → all
gates trip. Resolved by wiring `BP_AGVSimController.AGVActorClass = BP_AGVActor` and assigning the
`StateTreeComponentSchema` asset to `BP_AGVActor.TaskComponent.LifecycleStateTree`. The component
logs the exact failure (`"StateTree control is not running…"`) when this is misconfigured.

### PIE test harness (no backend / :7777 needed)
`IConsoleManager`-registered console commands on `AAGVSimController` (registered in BeginPlay,
freed in EndPlay) so the cell can be driven inside PIE: `Vcore.Start [Speed] [AgvCount]`,
`Vcore.Stop`, `Vcore.Assign <agvIndex>` (delivery pickup→load→dropoff→unload cascade),
`Vcore.Station <agvIndex> <stationId>` (retarget to a station dock). `Vcore.Start` mirrors the
HTTP start handler's state setup minus WebSocket/session correlation.

Also removed the redundant `TaskComponent->StopRun()` call in `AAGVActor::Configure` — it ran at
spawn before the StateTree control was started, so it only emitted benign
`AGVTaskComponent[]: blocking 'stop_run'/'transition' … StateTree not running` warnings (one pair
per AGV) for a no-op reset of an already-Offline fresh component.

### Auto-dispatch on sim start (2026-06-12)
`start_simulation` previously spawned the AGVs in `Idle` and left them there — nothing called the
(dead) `LoadingDockActor::AssignNextTask` hook, so the cell only moved via the chat
`/agv/command` drive path or the console harness. Wired `AAGVSimController::DispatchIdleAgvs()`:
runs once at the end of `StartRuntimeSimulation` and then on a 1.5 s repeating timer
(`AutoDispatchTimerHandle`, cleared in `StopRuntimeSimulation`), assigning `AssignDeliveryTask`
to every `IsAvailableForDispatch()` AGV so they continuously run the
pickup→load→dropoff→unload loop. Skips when `bSimPaused`. Chat `/agv/command` still overrides
specific AGVs (only picks Idle ones, so the two don't fight over a busy AGV).

> Note: an earlier attempt used `UFUNCTION(Exec)`, which the console reported as
> "Command not recognized" — Exec functions only route through PlayerController / Pawn /
> GameMode / HUD / GameInstance / CheatManager, not a plain `AActor`. Real console commands
> are globally reachable and avoid that routing constraint. Requires a C++ rebuild.

---

## Phase 10 — Production-grade UE5 refactor (P6) (2026-06-12)

### P6.0 — Architecture design (complete; gates P6.1–P6.3)
Produced the grounded architecture-design deliverable for the UE5 subsystem refactor in
[docs/spec_p6_refactor.md](docs/spec_p6_refactor.md), based on a full source read of
`Source/VCORE` (line counts, header responsibilities, dead-code confirmation via grep).

- **Class audit (§1)** — current vs. target responsibility for all 14 sim classes, with measured
  line counts and per-class demo-fakery flags. Headline findings: `AAGVActor` (778/179) is a
  God-actor mixing movement + `EAGVState` + traffic + battery + chase camera + nameplate + task +
  KPI; `ATrafficManagerActor` and `AIntersectionManager` are duplicate reservation queues
  (`AGVActor.cpp:548-549` picks one or the other); `ALoadingDockActor::AssignNextTask` is confirmed
  dead (never called externally); the autonomous loop bypasses the dispatcher via
  `AssignDeliveryTask(nullptr)` (`AGVSimController.cpp:1161`,`:1290`); station metadata
  (`Capacity`/`CapabilityTags`/`ZoneId`) is authored but never read; two state machines
  (`EAGVState` 8-state vs `EAGVTaskLifecycleState` 12-state) compete.
- **Target architecture (§2)** — component-first (Lyra-derived) layout that keeps the authoritative
  `public/`+`private/` purpose-subdir convention (spec_unreal §11.3) rather than the flat PLAN
  sketch. New units: `UAGVMovementComponent`, `UAGVTaskRunnerComponent`,
  `UStationInteractionComponent`, `USimEventBus`. Removed: `AIntersectionManager` (merged into
  traffic), `ALoadingDockActor` (subsumed by stations), `EAGVState`, and the `AGVStateTree*` runtime.
  Folds in the Part 11 P3/P4 Net/Camera extraction.
- **Event-driven contract (§3)** — two tiers: local typed dynamic-multicast delegates
  (`OnLifecycleChanged`, `OnMotionChanged`) and a PIE-scoped `USimEventBus` (`UWorldSubsystem`) with
  a 6-event catalog (AgvStateChanged, StationArrived, Reservation granted/released, Task
  completed/failed, CollisionDetected, BottleneckDetected) replacing today's direct `Emit*`/`Notify*`
  calls, preserving the Net/Domain layering rule. Migration ordered P6.1a→P6.3, each step compiling.
- **Three decisions surfaced for sign-off (§5)** gate P6.1: battery (recommend remove), StateTree
  runtime (recommend retire), LoadingDock (recommend delete/subsume). All three **confirmed** by the
  user 2026-06-12 (remove / retire / delete-&-subsume).

### P6.1a — Sim event bus (indirection step; no behavior change)
Introduced the event-driven backbone from the design contract (§3) as a pure indirection step ahead
of the de-faking work. New `USimEventBus` (`UWorldSubsystem`, PIE-scoped) in
`public|private/Events/`, with `SimEventTypes.h` payload structs and four C++ multicast delegates.

- Routed the four existing direct controller calls through the bus: `AAGVActor` now `Broadcast*`s
  `FSimAgvStateChangedEvent` / `FSimTaskCompletedEvent` / `FSimCollisionEvent` / `FSimBottleneckEvent`
  instead of calling `Controller->EmitAgvStateChange/NotifyTaskCompleted/NotifyCollision/EmitBottleneckEvent`.
- The controller is the sole subscriber: `BindSimEventBus()` in `BeginPlay` binds `Handle*` handlers
  (the former `Emit*`/`Notify*` bodies, unchanged), `UnbindSimEventBus()` in `EndPlay` calls
  `RemoveAll(this)` — matching the existing PIE-restart discipline so no stale callbacks survive.
- Behavior is identical (single synchronous subscriber, same JSON, same HUD/cinematic side effects).
  Non-dynamic delegates chosen since all producers/subscribers are engine-side C++. `public/Events`
  registered in `VCORE.Build.cs`. **Requires a C++ rebuild** (new UCLASS/USTRUCT → UHT).
- StationArrived + reservation-grant/release events from the §3 catalog are deferred to P6.1b/P6.2,
  where their producers (`UStationInteractionComponent`, the merged traffic manager) are introduced.

### P6.1b — Station interaction by proximity (de-fake the autonomous pickup/dropoff)
Replaced the hardcoded spline-ratio pickup/dropoff checkpoints with real proximity interaction driven
by `EStationKind`, fulfilling the first P6.1 bullet.

- New `UStationInteractionComponent` (a `USphereComponent` trigger, in `public|private/Component/`,
  radius 250 cm, Pawn-profile query-only mirroring the AGV's own sphere so overlaps fire identically to
  the proven AGV-AGV path). `AStationActor` now attaches one — stations went from fully passive to
  active interaction anchors.
- On AGV overlap the component broadcasts the new `FSimStationArrivedEvent` on the bus **and** calls
  `AAGVActor::HandleStationArrival(Station)` directly (deterministic, not subscription-order dependent).
  `HandleStationArrival` transitions MovingToPickup→Loading on a `Pickup` station and
  MovingToDropoff→Unloading on a `Dropoff` station (strict kind match).
- Deleted `PickupDistanceRatio`/`DropoffDistanceRatio` and their branches in
  `HandleCheckpointTransitions` (which now only serves the commanded `MovingToStation` docking
  checkpoint, still distance-based on a real station location).
- `AAGVSimController::EnsureInteractionStations()` guarantees the loop has stations to hit: if the level
  authors neither a Pickup nor a Dropoff station, it seeds a pair per AGV path at the former 0.22/0.72
  positions (now real trigger actors, not fakery). Designer-authored Pickup+Dropoff stations take
  precedence (no seeding). Seeded stations are tagged `RuntimeInteractionStation` and destroyed on
  teardown alongside the existing `RuntimeFallbackStation` cleanup.
- The controller subscribes `StationArrived` → pushes an `ARRIVE <agv> @ St<id> (<kind>)` line to the
  web HUD ticker, giving the new event a live consumer.
- **Requires a C++ rebuild.** Known limit: pure-overlap detection can tunnel at very high sim-speed
  multipliers; fine at demo speeds (radius 250 cm). Smoke check after rebuild: run the autonomous loop
  and confirm AGVs still Load/Unload (now at the seeded Pickup/Dropoff stations) and tasks complete.

### P6.1c — Dispatcher as sole assignment authority + station metadata in scoring
Closed the "dispatcher consulted only on the command path" gap and made the authored station metadata
meaningful.

- `AAGVSimController::DispatchIdleAgvs` no longer calls `AssignDeliveryTask(nullptr)` directly. It
  gathers the Pickup stations and, for each available AGV, asks the new
  `ADispatcherActor::SelectStationForAgv(Agv, PickupStations, score)` (AGV-centric selection) — the AGV
  is assigned a delivery only when an eligible Pickup station exists. A degraded fallback (assign
  directly) remains only if no dispatcher is present. The dispatcher is now the single assignment
  authority for both autonomous and commanded flows.
- `ADispatcherActor::ScoreAgvForStation` now gates eligibility on `Station->Capacity > 0` and folds the
  three previously-unread metadata fields into `StationScore`: capacity (`min(Capacity,4)*5`, 0–20,
  throughput), `CapabilityTags` breadth (`min(Num,5)*2`, 0–10, richer anchors), and a configured
  `ZoneId` (+5). All three surface in the dispatch `Explanation` for observability. `SelectStationForAgv`
  picks the highest-scoring eligible station; ETA-based distance naturally selects the AGV's on-path
  Pickup.
- Removed `CreateFallbackStation` (method + header decl + its sole empty-registry call site) — that
  case is now covered by `EnsureInteractionStations` (P6.1b), which seeds real Pickup/Dropoff pairs.
  Teardown station cleanup now tracks only the `RuntimeInteractionStation` tag.
- **Demo-scope:** capacity is a single-slot eligibility gate (not N-occupancy reservation) and
  capability/zone are tie-breaker signals, not a full matching/zone-routing subsystem (out of scope per
  the demo-prototype rule). **Requires a C++ rebuild.** Smoke check: autonomous loop still runs (AGVs
  keep getting assigned and completing deliveries); dispatch explanation now shows `cap=/capability=/zone=`.

### P6.1d — Remove fake battery, delete LoadingDock, lift config hardcodes (completes P6.1)
The final de-faking step. All three locked decisions executed.

- **Battery: removed, then restored by request (net: unchanged).** P6.1d first deleted the fake battery
  end-to-end, but a battery readout turned out to be needed for the demo, so it was **restored
  2026-06-12**: `AAGVActor::BatteryPercent` (flat `0.15/s` drain, floored at 20%, reset to 100% on
  configure) + `GetBatteryPercent()`, the dispatcher `BatteryScore` term, the `Battery` field on
  `FSimAgvStateChangedEvent`, the `battery` key in the `AGV_STATE_CHANGE` event/demo/telemetry JSON, the
  F2 billboard readout, and the web `BatteryBar` gauge (`chat-web` `App.tsx` + `AgvTelemetry.battery` type
  + `.batteryBar` CSS). Still a fake model — no real charge/discharge or `Charger` station.
- **`ALoadingDockActor` deleted.** Removed the class (`.h`/`.cpp`) and every reference: the controller
  spawn/validity-check/Configure-arg/Destroy/ResetForRun, the AGV `Configure` parameter + member + the
  `CompleteTask` call. Its task counter was already redundant with `UKPIAccumulator` (fed by the bus
  `TaskCompleted`), and `AssignNextTask` was dead. `AAGVActor::Configure` lost its `InLoadingDockActor`
  parameter.
- **Config hardcodes lifted.** `BaseMoveSpeed` (220 cm/s) and `ActionDurationSeconds` (1 s) are now
  `UPROPERTY(EditAnywhere, Category="VCORE|AGV|Movement", meta=(AllowPrivateAccess, ClampMin))` on
  `AAGVActor` — editor-authored config, replacing the `// TODO: config` hardcodes (kept simple; no
  DataAsset, per the demo-prototype rule).
- **P6.1 is complete** (station interaction + station metadata + battery + dead paths all done).
  **Requires a C++ rebuild** (and a `chat-web` rebuild for the overlay). Deleted files +
  `LoadingDockActor` removal need P4 reconcile (mark-for-delete). Smoke check: autonomous loop runs;
  deliveries still complete; the battery gauge/readout is back (billboard, web `BatteryBar`, telemetry).

## Single-Model Serving — Adapter Toggle (2026-06-15)

VRAM allows only one model, but the system needs tool routing + general chat + reporting.
Collapsed the two-model `routing_split` into ONE host llama.cpp model: base `qwen3.5:2b` +
the integrated path/action routing LoRA, with the adapter toggled **per request** (scale 1.0
for `propose_tool_call` = SFT router; scale 0.0 for chat/plan/report = bare base). Backend:
`adapter_scale` on `LlamaCppLlmGateway` (injects the per-request `lora` field), new
`PathActionRoutingGateway` (parses this model's `{"route","action","arguments"}` schema under
`path_action_system.txt`), new `LLM_PROVIDER=adapter_toggle` in `container.py`, scales in
`config.py`. Adapter GGUF (21.8 MB) at `docs/sft/integrated/data/vcore-path-action-router-adapter-f16.gguf`.
Deployed: `web/.env` set to `adapter_toggle`; host llama-server on :8080 relaunched with
`--lora <adapter> --lora-init-without-apply`; backend rebuilt via `docker compose up --build -d`.
Verified: `/llm/status` = adapter_toggle ready; routing creates correct commands; routing 99.4%
on the test set; chat/report defect-free; intent classification identical to the old Ollama path.
Full detail: [docs/sft/integrated/RESULT_PATH_ACTION_SFT.md](docs/sft/integrated/RESULT_PATH_ACTION_SFT.md).
