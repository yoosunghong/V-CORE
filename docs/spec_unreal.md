> **CANONICAL UE5 SPEC (unified 2026-06-07).** This file is the single source of truth for the
> Unreal Engine 5 subsystem. It merges the former two UE5 docs:
> - the **runtime/behaviour** spec (this file's original content — Parts 1–10), and
> - the **architecture & directory partitioning** plan (previously `spec_unreal_architecture.md`,
>   now folded into **Part 11** below; that file is a redirect stub).
>
> Portfolio-facing feature extensions (real-time visualization, 3D rendering, AI-agent scenario
> verification) are specced in [spec_portfolio_features.md](spec_portfolio_features.md) and summarized
> in **Part 12**.
>
> **UPDATED (2026-06-04):** `AGVSimController` gained Virtual Process control routes
> (`/sim/pause`, `/sim/resume`, `/sim/speed`, `/agv/command`, `GET /sim/status`) and now
> posts chat-correlated events to the backend ingest webhook. See
> [spec_virtual_process.md](spec_virtual_process.md). The AGV-cell runtime below is current.

# UE5 Simulation Specification

**Project:** VCORE — AI Twin Platform  
**Subsystem:** Unreal Engine 5 AGV Cell Simulation  
**Version:** 0.2 (Demo Prototype — unified runtime + architecture)

---

## Part Index

| Part | Topic |
|---|---|
| 1–10 | **Runtime / behaviour spec** — scene, classes, state machine, control logic, events, HUD, data transmission, KPIs, build notes |
| 11 | **Architecture & directory partitioning** — layering, God-Class decomposition, target tree, migration phases |
| 12 | **Portfolio feature extensions** — pointer to [spec_portfolio_features.md](spec_portfolio_features.md) |

---

## 1. Overview

The UE5 module is a 3D virtual industrial cell containing 3 Automated Guided Vehicles (AGVs) that follow fixed spline paths. It receives simulation commands from the web backend, executes the scenario, streams real-time events, and submits a final JSON report upon completion or stoppage.

---

## 2. Scene Composition

### 2.1 Physical Layout

| Element | Count | Notes |
|---|---|---|
| AGVs | 3 | Static mesh actors with physics-based collision |
| Spline Paths | 4 | Fixed routes forming a loop with one intersection |
| Intersection | 1 | Single crossing point; priority logic applied here |
| Loading Dock | 1 | Task source/sink; AGVs pick up and deliver here |
| Cell Boundary | 1 | Static mesh walls defining the operational area |

### 2.2 Path Topology

```
[Dock A] ──── Path1 ────> [Intersection X] ──── Path3 ────> [Dock B]
                                   ^
                                   │ Path2 / Path4 (bidirectional loop)
                                   │
                              [Staging Zone]
```

- All paths are UE5 Spline Components.
- AGVs follow spline tangent direction; speed is configurable via `Start_Sim` parameters.
- Path2 and Path4 are the approach/exit arms of the intersection loop.

---

## 3. C++ Class Structure

> **Current on-disk layout (2026-06-07):** headers live under `public/<purpose>/`, cpp under
> `private/<purpose>/` — see the partitioned tree in **Part 11.3**. The table below lists the actual
> classes by purpose. `SimEventDispatcher` / `KPIAccumulator` were *planned* as separate units but
> currently live inside `AGVSimController`; their extraction is Phase 8 P2–P3.

| Purpose subdir | Class (header / cpp) | Role |
|---|---|---|
| `controller/` | `AGVSimController` | Main actor: receives commands, manages sim lifecycle |
| `actor/` | `AGVActor` | Individual AGV: movement, state machine, event emission |
| `actor/` | `AGVPathActor` | Authored spline holder (route geometry) |
| `actor/` | `IntersectionManager` | Priority/FIFO logic for intersection access |
| `actor/` | `LoadingDockActor` | Task generator: assigns pickup/delivery tasks to AGVs |
| `component/` | `SplinePathComponent` | Spline follower component |
| `visualization/` | `CongestionHeatmapComponent`, `AGVStatusBillboardComponent` | Portfolio viz (Part 12) |
| `cinematics/` | `CinematicEventDirector` | Portfolio camera (Part 12) |
| `scenario/` | `ScenarioVerificationComponent` | Portfolio AI verification (Part 12) |
| `metrics/` *(planned)* | `KPIAccumulator` | Raw counters → final KPI calc (currently in controller) |
| `net/` *(planned)* | `SimEventDispatcher` + boundary | Event/telemetry transport (currently in controller) |

---

## 4. AGV State Machine

Each `AGVActor` has the following states:

```
IDLE ──(task assigned)──> MOVING_TO_PICKUP
MOVING_TO_PICKUP ──(arrived)──> LOADING
LOADING ──(load complete)──> MOVING_TO_DROPOFF
MOVING_TO_DROPOFF ──(arrived)──> UNLOADING
UNLOADING ──(unload complete)──> IDLE
MOVING_TO_PICKUP / MOVING_TO_DROPOFF ──(collision detected)──> STOPPED_COLLISION
MOVING_* ──(bottleneck wait > threshold)──> WAITING_AT_SECTION
WAITING_AT_SECTION ──(path clear)──> MOVING_*
STOPPED_COLLISION ──(manual resume / sim end)──> IDLE
(authored AGV excluded from the run: index >= agv_count) ──> STOPPED_OPERATION
```

State transitions emit `SimEvent` JSON objects (see API spec).

**Offline reset (`STOPPED_OPERATION`).** `AuthoredAgvs` is the level's full pre-placed AGV
set; on sim start only the **highest-index** `agv_count` entries are configured and run (running
3 of 5 activates indices 2–4 and parks 0–1). The remainder are
**not** left frozen in their previous-run pose — each is reset via
`AAGVActor::ResetToStoppedOperation()` (home pose captured at `BeginPlay`, battery 100%, no
task/order, stale traffic/intersection pointers dropped) and parked in `STOPPED_OPERATION`.
`EmitTelemetry` reports **all** authored AGVs (active + offline), so the dashboard AGV list shows
every offline unit as a red "가동 정지 / Stopped Operation" card instead of dropping it or leaking
the previous run's position/battery. Offline AGVs are collision-inert (overlapping one never
registers a collision).

---

## 5. Control Logic

### 5.1 Receiving the Start Command

`AGVSimController` exposes an HTTP server on a configurable local port (default: `7777`).

**Endpoint:** `POST http://localhost:7777/sim/start`

**Request body:** See [spec_api.md §3.1](spec_api.md).

On receipt:
1. Parse `speed`, `duration`, `policy_id`.
2. Apply `speed` as the base movement speed multiplier for all AGVs.
3. Set simulation timer for `duration` seconds (simulated time).
4. Apply `policy_id` to `IntersectionManager` (see §6).
5. Start all AGVs in `IDLE` → assign initial tasks.

Demo fallback note:
- During the current integration phase, `AAGVSimController` may emit placeholder `AGV_STATE_CHANGE` and `SIM_PROGRESS` events and auto-submit a completion payload within 10 real seconds.
- This fallback exists only to prevent demo runs from remaining stuck in `running` status before the real AGV loop is implemented.

Threading note:
- The embedded UE5 HTTP server may execute request handlers off the game thread.
- `AAGVSimController` must dispatch any `UWorld`, timer, actor spawn/destroy, or WebSocket lifecycle work onto the game thread before executing it.
- HTTP worker-thread code must not create or validate `TWeakObjectPtr` instances for live actors before the handoff. Capture raw pointers only, then validate them on the game thread.
- HTTP worker-thread code must also avoid reading or mutating actor-owned run state such as `bSimRunning` or `ActiveParams`; those checks belong on the game thread too.
- Start/stop endpoints should return their HTTP response immediately after validation, then queue the simulation state change on the game thread.
- PIE lifecycle note: when a PIE world ends, `AAGVSimController` must unbind its `/sim/start` and `/sim/stop` routes and clear active-run state locally so a restarted PIE session never reuses stale HTTP callbacks or stale `bSimRunning` state from the previous world.

### 5.1.1 Phase 2.1 Demo Implementation

The playable loop is authored in the editor so the demo can use Blueprint visuals and level-placed splines instead of hardcoded control points.

- `AAGVSimController` still owns sim lifecycle, HTTP/WebSocket, and runtime spawning.
- `AAGVSimController` exposes an editable `AGVActorClass` so a Blueprint child of `AAGVActor` can be selected in `BP_SimController`.
- `AAGVSimController` also exposes an ordered list of authored `AAGVPathActor` references placed in the level.
- `AAGVPathActor` owns the spline geometry. The spline is edited on the path actor or on a Blueprint derived from `AAGVPathActor`, not on the moving AGV actor itself.
- Each spawned AGV is assigned one authored spline reference plus its initial distance offset, then samples world-space position/rotation from that spline during movement.
- `ALoadingDockActor` immediately assigns a new delivery cycle when an AGV finishes unloading so throughput can be measured continuously.
- `AIntersectionManager` controls a single shared intersection segment using FIFO queueing only for now.
- If runtime initialization is missing required authored references, the controller may still fall back to the placeholder demo flow instead of leaving the backend run stuck.

### 5.1.2 Path Authoring Rule

- A moving `AAGVActor` must not own the spline it follows.
- If the spline component is attached to the same actor that is being translated every tick, the spline moves with the AGV and the AGV no longer follows a stable world path.
- The correct structure for this demo is:
  - authored level actor: `AAGVPathActor` with `USplineComponent`
  - moving runtime actor: `AAGVActor` with mesh/collision/state machine
  - runtime link: `AAGVActor` stores a reference to the authored spline component and samples it
- A Blueprint child of `AAGVActor` can still customize visuals, collision, materials, and other actor properties, but route geometry should remain external.

### 5.1.2.1 AGV → Path Assignment & Staggered Launch

AGVs are level-placed and never spawned/destroyed at run time; on sim start the active set is
connected to the authored paths and driven along them. The assignment in
`InitializeRuntimeSimulationActors()` is:

- **Active selection (highest index first).** The active set is the top `agv_count` entries of
  `AuthoredAgvs` (indices `Num()-agv_count … Num()-1`). Lower indices are reset to
  `STOPPED_OPERATION`. Auto-discovery now pulls **every** level-placed `AAGVActor` into
  `AuthoredAgvs` (name-sorted), so it is no longer capped by the path count.
- **Round-robin path mapping, evenly spaced.** Active AGVs are mapped to the valid paths
  round-robin (`Slot % PathCount`), so they spread as evenly as possible across the routes — e.g.
  5 AGVs over 3 paths → 2,2,1 — instead of all piling onto whichever spline they sit nearest (the
  old `FindClosestSplinePoint` nearest-path logic, which clustered multiple AGVs onto one path and
  collided them on the first frame). AGVs that share a path get an **entry distance** spaced evenly
  along its spline (`SplineLength * SlotOnPath / UnitsOnPath`), so same-path units never converge on
  one point. Only ≥ 1 valid path is required.
- **Drive to the path (no teleport).** AGVs no longer snap onto the spline at run start. Each AGV
  stays at its placed home pose and, once it starts moving, drives in a straight line to its
  assigned entry point (`UAGVMovementComponent::TickApproach`, gated by `bApproachActive`). On
  reaching the path it locks onto the spline and hands off to the normal spline follower. This
  replaces the snap-onto-spline teleport that dropped every AGV onto its route at once.
- **Staggered launch in time.** `StartRuntimeSimulation` starts the first AGV immediately and each
  subsequent AGV `AgvStartStaggerSeconds` (default 3.0) later via one-shot timers. Because an AGV
  is only dispatchable once `StartRun` sets `bRunActive`, this also staggers when each unit first
  picks up work and begins its approach — preventing a simultaneous pile-up on start.
  Timers are guarded on `bSimRunning && !bSimPaused` and cleared on stop.

### 5.1.3 Skeletal-Mesh Animation Rule

- The AGV is translated procedurally every tick (`SetActorLocation`/`SetActorRotation` from the
  sampled spline); it has **no movement component**, so the engine's default
  `AActor::GetVelocity()` would report zero and a skeletal-mesh Animation Blueprint would never
  drive its idle↔drive locomotion blend.
- `AAGVActor` therefore overrides `GetVelocity()` to return `GetActorForwardVector() * CurrentSpeed`.
  A standard locomotion AnimBP can read motion via **GetOwningActor → GetVelocity** (the `Speed` =
  `VectorLength(Velocity)` pattern) with no extra wiring.
- For AnimBP graphs that prefer explicit inputs, `AAGVActor` also exposes `GetCurrentSpeed()`,
  `IsMoving()`, and `GetStateName()` as `BlueprintPure` accessors.

### 5.2 Simulation Speed Multiplier

- `speed` in `Start_Sim` is a multiplier: `1.0` = real-time, `60.0` = 1 sim-minute per real second.
- Applied via `UGameplayStatics::SetGlobalTimeDilation`.
- Event timestamps are stored in **simulated time**, not wall-clock time.

### 5.3 Policy IDs (Demo)

| `policy_id` | Description |
|---|---|
| `POLICY_FIFO` | Intersection: first-come-first-served |
| `POLICY_PRIORITY_LOADED` | Loaded AGVs get intersection priority |
| `POLICY_ROUND_ROBIN` | Intersection access rotates by AGV ID |

---

## 6. Event Detection

### 6.1 Collision Detection

- Uses UE5 `OnComponentBeginOverlap` on AGV mesh collision capsule.
- On overlap with another AGV mesh:
  1. Both AGVs transition to `STOPPED_COLLISION`.
  2. Emit `CollisionEvent` with positions, velocities, and involved AGV IDs.
  3. Log to `SimEventDispatcher`.
  4. Simulation does **not** auto-stop; both AGVs remain stopped until sim ends.

### 6.2 Bottleneck Detection

- `IntersectionManager` tracks wait time per section per AGV using `FPlatformTime::Seconds`.
- Threshold: `10.0` simulated seconds (configurable via `Start_Sim.bottleneck_threshold_sec`).
- On threshold exceeded:
  1. Emit `BottleneckEvent` with section ID, AGV ID, wait duration.
  2. AGV transitions to `WAITING_AT_SECTION`.
  3. Warning is displayed in UE5 HUD.

---

## 7. HUD / In-UE UI

> **Widget review (2026-06-07): does UE5 need its own UI, beyond the web front-end?**
> The web `chat-web` overlay already renders the interactive 2D dashboard (metric cards, camera
> switcher, chat, scenario controls) as HTML *positioned over* the Pixel-Streamed iframe. So UE5 does
> **not** need to re-implement those. But two classes of UI genuinely belong **in the engine**,
> because the web overlay cannot produce them:
>
> 1. **World-space, depth-correct UI** — must track 3D positions with perspective/occlusion. Done by
>    **F2 `UAGVStatusBillboardComponent`** (per-AGV floating `state·battery·speed` label). A future
>    upgrade to a UMG `WidgetComponent` card is deferred (TextRender is asset-free and sufficient).
> 2. ~~**Screen-space UI baked into the video stream** — Done by F5 `AVCOREHud`.~~ **Removed
>    (2026-06-08):** the in-viewport HUD was migrated to the web overlay (§7.1). Its snapshot is now
>    streamed on the process telemetry frame and rendered as an HTML HUD over the Pixel-Streamed iframe.
>
> **Decision matrix:**
>
> | UI element | In UE5 | Web overlay | Why |
> |---|---|---|---|
> | Chat, scenario editor, run/speed controls | — | ✅ (done) | Interactive forms — HTML is the right tool |
> | 2D metric dashboard cards | — | ✅ (done) | Already driven from Firebase |
> | Camera switcher buttons | — | ✅ (done) | Control surface |
> | Per-AGV 3D labels | ✅ F2 | — | Must track world position |
> | Congestion floor heat | ✅ F1 | — | 3D world rendering |
> | Sim status / event ticker / verdict banner | — | ✅ (web HUD) | Streamed on the process telemetry frame; rendered as an HTML HUD (§7.1) |
> | Cinematic auto-camera | ✅ F3 | — | Engine camera |
>
> **Conclusion:** keep all 2D UI — including the sim status/ticker/verdict HUD — in the web overlay,
> and keep 3D-anchored UI in UE (F2). No `WBP_*` UMG assets are required — F2 uses
> `UTextRenderComponent`, and the HUD is plain HTML.

### 7.1 Sim status HUD — web overlay (was F5 `AVCOREHud`)

> **Migrated to the web (2026-06-08).** The in-viewport UE5 HUD (`AVCOREHud` + `UVcoreHudWidget`) was
> removed. The same content is now rendered as an HTML HUD (`VcoreHud` in `chat-web/src/App.tsx`,
> top-left of the viewport overlay), fed from the live process telemetry frame. This unifies the 2D UI
> in one place and made the live data path Firebase-independent (see [spec_virtual_process.md](spec_virtual_process.md)).

The HUD shows a dark panel anchored top-left: a status line, meta line, a progress bar, a counters
line, a verdict badge, and a recent-events ticker:

```
┌────────────────────────────────────────┐
│ VCORE VIRTUAL PROCESS            RUNNING │
│ Speed 60x · Progress 42% · Policy FIFO   │
│ ▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░                     │
│ Tasks 7 · Collisions 1                   │
│ ACCEPTANCE  FAIL (2/3 criteria)          │   ← verdict (green PASS / red FAIL)
│ RECENT EVENTS                            │
│   BOTTLENECK AGV-2 @ INTERSECTION_X (12s)│
│   COLLISION  AGV-1 x AGV-3               │
└────────────────────────────────────────┘
```

- **UE5 side:** `AAGVSimController::GetHudSnapshot()` (status, speed, progress, counters, recent-events
  ring buffer, verdict) is serialized onto the `kind:"process"` telemetry frame in
  `EmitTelemetry()` (`tasks_completed`, `collisions`, `policy_id`, `recent_events`, `verdict_summary`,
  `verdict_passed`). No HUD actor/widget remains; `AVirtualProcessGameMode` no longer sets `HUDClass`.
- **Transport:** UE5 → backend WebSocket → `LiveTelemetryHub` → `/unreal/telemetry/stream` SSE
  (`event: hud`). See [spec_virtual_process.md](spec_virtual_process.md) for the backend hub + SSE.
- **Web side:** the `VcoreHud` component renders the `hud` SSE frame; collision counts and
  `COLLISION`/`BOTTLENECK` event lines use an alert colour; the verdict badge is green on PASS, red on
  FAIL, and hidden when the run carried no acceptance criteria.

### 7.2 Per-AGV world labels — F2

See [spec_portfolio_features.md](spec_portfolio_features.md) §3. Replaces the previously-planned
`WBP_AGVStatusBar` / `WBP_SimMetaPanel` UMG widgets: the per-AGV data now floats in 3D (F2) and the
sim-meta panel is now the web overlay HUD (§7.1), so no `WBP_*` assets are needed.

---

## 7.3 Browser Camera View

The browser view is delivered through UE Pixel Streaming, not through the
`AGVSimController` JSON command server. The web backend exposes the configured
viewer URL with `GET /unreal/viewport`, and `chat-web` embeds that URL as the
main viewport on `http://localhost:5199`.

Expected local default:

```ini
UE5_VIEW_URL=http://localhost:8880
```

`UE5_VIEW_URL` must point at the Pixel Streaming **player page** (HTTP `:8880`), not the
streamer WebSocket port (`:8888`). Pointing it at `:8888` loads a page that cannot start a
WebRTC session, so the embedded viewport shows "DISCONNECTED. CLICK TO RESTART".

The UE5 command server remains responsible for command, status, and event DTOs.
Pixel Streaming remains responsible for video frames and optional interactive
camera input.

---

## 8. Data Transmission (Outbound)

### 8.1 Real-Time Event Stream

- `AGVSimController` may maintain a WebSocket client connection to:
  `ws://[backend_host]:[backend_port]/internal/ue5/stream`
- Events are sent immediately as they occur (no batching in demo).
- Message format: backend `DomainEvent` envelope with the original sim event under
  `payload`.
- In the demo controller implementation, `localhost` is normalized to `127.0.0.1` for UE5 WebSocket connections because loopback DNS resolution can fail during initialization on Windows.
- The UE5 client retries WebSocket connection up to 3 times with 2-second backoff before giving up, and the simulation must continue without crashing.

### 8.2 Final Report Submission

On simulation end (timer expires, all AGVs stopped, or `Stop_Sim` command received):

1. `KPIAccumulator` computes final KPIs from accumulated raw data.
2. `SimEventDispatcher` collects the full timeline log.
3. HTTP POST to `http://[backend_host]/api/v1/simulation/{run_id}/complete`
4. Payload: complete timeline + 4 KPIs. See [spec_api.md §3.3](spec_api.md).

### 8.2.1 Demo Fallback Completion

- In the current demo skeleton, `AAGVSimController` may generate placeholder KPI values and timeline entries directly.
- `POST /sim/stop` must immediately trigger a final report with `stop_reason = STOP_COMMAND`.

### 8.3 Authentication

All outbound HTTP/WebSocket requests include header:
```
X-AGV-API-Key: <pre-shared key from config>
```

Config file: `Config/DefaultGame.ini` section `[AGVSim]`:
```ini
[AGVSim]
BackendHost=localhost
BackendPort=8000
APIKey=demo-api-key-change-in-prod
RunId=
```

### 8.4 Data-Oriented Integration Boundary

UE gameplay classes should not leak actor pointers or Blueprint implementation
details into the web stack. External integrations use compact records:

- `ProcessTelemetry`: throughput, active AGVs, average wait time, collision risk,
  uptime, measured timestamp.
- `RobotCommand`: command id, session id, correlation id, command name, parameters.
- `DomainEvent`: event type, command id, session id, correlation id, payload.
- `UnrealViewport`: Pixel Streaming URL and telemetry SSE endpoint.

Actor state is reduced to these records at `AGVSimController` and backend
adapter boundaries. This keeps the web stack stable while UE gameplay internals,
Blueprint visuals, and path-authoring details evolve.

---

## 9. KPI Definitions (Raw Data Sources)

| KPI | Formula | Raw Data |
|---|---|---|
| Throughput | Tasks completed / simulated hour | `LoadingDockActor` task completion counter |
| Avg Wait Time | Sum of all section wait times / total AGV-section visits | `IntersectionManager` wait time accumulator |
| Collision Risk | Collision events / simulated hour | `CollisionEvent` count |
| Uptime | Time in active task states / total sim time per AGV, averaged | AGV state machine time-in-state counters |

> **Autonomous task completion (2026-06-12).** Throughput depends on AGVs actually completing
> Load→Unload cycles. Arrival at a Pickup/Dropoff station is detected two ways: the primary path is
> the station's `UStationInteractionComponent` physics overlap; a deterministic fallback,
> `AAGVActor::CheckAutonomousStationArrival` (per tick, via
> `AAGVSimController::FindNearestStationOfKind`), registers arrival by distance so the cell keeps
> completing tasks — and the run-report KPIs stay non-zero — even if the overlap doesn't fire under
> the project's collision-channel responses. Both route through the state-guarded
> `AAGVActor::HandleStationArrival`, so they never double-count an arrival.

---

## 10. Build Notes

- UE5 version: 5.3+
- Plugin dependencies: none (uses engine-only features for demo)
- HTTP client: `FHttpModule` (engine built-in)
- WebSocket client: `IWebSocket` from `WebSockets` module — add to `VCORE.Build.cs`:
  ```csharp
  PublicDependencyModuleNames.AddRange(new string[] {
      "Core", "CoreUObject", "Engine", "WebSockets", "HTTP", "Json", "JsonUtilities"
  });
  ```

---

# Part 11 — Architecture & Directory Partitioning

> **Merged from the former `spec_unreal_architecture.md` (2026-06-07).** Goal: turn the current
> single-folder, template-derived module into a **feature-partitioned, production-grade C++ layout**
> with a clear layered architecture, without breaking the running demo. This is the UE5 counterpart
> to the web stack's DDD/hexagonal layout. Tracked as **Phase 8** in [PLAN.md](../PLAN.md).

## 11.1 Current State

The actual AGV sim lives under `Source/VCORE/public/` + `private/` (6 file pairs). Alongside it sit
TopDown-template leftovers (`Variant_TwinStick/`, removed `Variant_Strategy/`,
`VCORECharacter`/`VCOREPlayerController`/`VCOREGameMode`) — see the **Legacy** section in
[../README.md](../README.md) and Phase 8/P0 in [PLAN.md](../PLAN.md).

### Problems

1. **God Class.** `AGVSimController` (~1622 lines) owns *everything*: config load, an 8-route HTTP
   server, a WebSocket client, three telemetry transports (UDP/TCP/WS), demo-fallback timers, the
   runtime sim lifecycle, KPI accumulation, chat-correlated event posting, and camera control. This
   is the single biggest maintainability and merge-conflict risk.
2. **Planned-but-never-extracted classes.** `SimEventDispatcher` and `KPIAccumulator` were promised
   as separate units (see Part 3.1 of this spec) but folded into the controller instead.
3. **Flat `public/`+`private/`.** Network code and pure domain code are not separated, violating the
   project rule "domain classes have no network dependencies".
4. **Template dead weight on the build path.** Variant/template files remain in `VCORE.Build.cs`
   `PublicIncludePaths`; none are referenced by the AGV sim.

## 11.2 Target Architecture — Layering (dependencies point inward only)

```
┌──────────────────────────────────────────────────────────────┐
│ Boundary / IO          Net/  ── HTTP server, WS client,       │
│ (talks to backend)            telemetry transports, ingest    │
│        │ depends on ▼                                          │
├──────────────────────────────────────────────────────────────┤
│ Application            Simulation/AGVSimController             │
│ (orchestration)        — run lifecycle, command dispatch,      │
│                          owns subordinate components           │
│        │ depends on ▼                                          │
├──────────────────────────────────────────────────────────────┤
│ Domain                 Simulation/Agents + Infrastructure,     │
│ (no network deps)      Metrics/, Visualization/, Scenario/     │
└──────────────────────────────────────────────────────────────┘
```

**Rule (enforced):** Domain folders (`Simulation/Agents`, `Simulation/Infrastructure`, `Metrics`,
`Visualization`, `Scenario`) must not `#include` anything under `Net/`. All HTTP/WS/socket includes
live under `Net/` only. The orchestrator (`AGVSimController`) is the only class that holds both a
domain reference and a `Net/` reference.

### Responsibility split (decompose the God Class)

| New unit | Type | Extracted responsibility |
|---|---|---|
| `AGVSimController` | `AActor` | Run lifecycle + command dispatch only; delegates IO/metrics |
| `USimNetworkComponent` | `UActorComponent` | HTTP server (8 routes), request parsing/responding |
| `USimEventDispatcher` | `UObject` | WS client + chat-correlated `/internal/ue5/events` posting |
| `UTelemetryEmitter` | `UActorComponent` | UDP/TCP/WS transport selection + 5 Hz frame emit |
| `UKPIAccumulator` | `UObject` | Counters (tasks, collisions, uptime) + final report build |
| `UCameraDirector` | `UObject` | `SetViewTargetWithBlend` to per-AGV cameras |
| `FSimJson` | static lib | Centralized JSON build/parse (`ParseRequestBody`, builders) |

Each handler in `USimNetworkComponent` forwards a parsed, validated struct to the controller via a
typed call (`StartRun(FSimStartParams)`, `PauseRun()`, `SetSpeed(float)`, `DispatchAgvCommand(...)`),
keeping the boundary/parse logic out of the orchestrator.

## 11.3 Directory Layout (adopted convention)

> **Convention (authoritative, 2026-06-07):** the module keeps the Unreal `public/` (headers) +
> `private/` (cpp) split. Inside *each* of those, files are partitioned into **purpose
> subdirectories** that mirror the layering in 11.2. A class's header and cpp live in the
> same-named subdirectory under `public/` and `private/` respectively. The layering rule (11.2) is
> enforced by which subdirectory a file lives in, not by a separate top-level tree.

```
Source/VCORE/
├── VCORE.Build.cs                 ← public/* subdirs registered in PublicIncludePaths
├── VCORE.{h,cpp}                  ← module entry + LogVCORE
│
├── public/                         ← all headers, partitioned by purpose
│   ├── controller/   AGVSimController.h                 (APPLICATION — orchestrator)
│   ├── actor/        AGVActor.h, AGVPathActor.h,
│   │                 IntersectionManager.h, LoadingDockActor.h   (DOMAIN — AActors)
│   ├── component/    SplinePathComponent.h               (DOMAIN — components)
│   ├── visualization/ CongestionHeatmapComponent.h,
│   │                  AGVStatusBillboardComponent.h       (DOMAIN — data-driven 3D viz)
│   ├── cinematics/   CinematicEventDirector.h             (presentation — camera)
│   ├── scenario/     ScenarioVerificationComponent.h      (DOMAIN — AI verification)
│   │   ── planned extractions (Phase 8 P2–P4) ──
│   ├── metrics/      KPIAccumulator.h                     (DOMAIN)
│   ├── net/          SimNetworkComponent.h, SimEventDispatcher.h, SimJson.h,
│   │                 telemetry/TelemetryEmitter.h, telemetry/TelemetryTransport.h  (BOUNDARY)
│   └── core/         VirtualProcessGameMode.h  (framework glue; HUD migrated to the web overlay, §7.1)
│
└── private/                        ← matching cpp under the same purpose subdirs
    ├── controller/   AGVSimController.cpp
    ├── actor/        AGVActor.cpp, AGVPathActor.cpp, IntersectionManager.cpp, LoadingDockActor.cpp
    ├── component/    SplinePathComponent.cpp
    ├── visualization/ CongestionHeatmapComponent.cpp, AGVStatusBillboardComponent.cpp
    ├── cinematics/   CinematicEventDirector.cpp
    ├── scenario/     ScenarioVerificationComponent.cpp
    └── … metrics/ net/ core/ as extracted …
```

> `private/` is auto-added to the module's private include path; `.cpp` files are compiled by UBT's
> recursive glob and never `#include`d, so their subdivision is organizational only. Header
> subdirectories under `public/` are registered explicitly in `VCORE.Build.cs`
> (`PublicIncludePaths`) so bare-name includes (`#include "AGVActor.h"`) keep resolving regardless of
> `bLegacyPublicIncludePaths`. **Net/Domain rule:** files under `public/actor`, `public/component`,
> `public/metrics`, `public/visualization`, `public/scenario` must not include anything from
> `public/net` — only `public/controller` (the orchestrator) may include both.

### Optional: multi-module split (defer)

A stricter production layout would promote `Net/` to its own Runtime module (`AGVSimNet`) so the
domain module literally *cannot* link sockets. **Deferred** — marginal benefit at demo scale.

## 11.4 Migration Phases (each independently compilable)

- **P0 — Remove legacy (no behaviour change).** Delete remaining `Variant_TwinStick/` if unreferenced
  by maps; strip matching `PublicIncludePaths` lines; author the Virtual Process GameMode. *(Verify
  map/GameMode references first.)*
- **P1 — Purpose partition (move only). ✅ DONE 2026-06-07.** The 6 existing sim files were moved into
  `public|private/{controller,actor,component}/`; the new portfolio classes into
  `{visualization,cinematics,scenario}/`. Pure file moves; bare includes preserved via registered
  `PublicIncludePaths`.
- **P2 — Extract Metrics.** Pull KPI counters/report build into `UKPIAccumulator`
  (`public|private/metrics/`).
- **P3 — Extract Net boundary.** HTTP server → `USimNetworkComponent`, WS+ingest →
  `USimEventDispatcher`, telemetry → `UTelemetryEmitter`, JSON → `FSimJson` (all under
  `public|private/net/`). Controller exposes typed `StartRun/PauseRun/SetSpeed/DispatchAgvCommand`.
- **P4 — Camera + cleanup.** Extract `UCameraDirector` (`public|private/core` or `cinematics/`);
  controller `Tick` only advances run state. Run `ue-architecture-lint` / `ue-perf-lint` to confirm
  God Class + Tick-abuse flags clear.

**Done when:** `AGVSimController.cpp` is < ~400 lines, no file under `actor/`, `component/`, `metrics/`,
`visualization/`, or `scenario/` includes a socket/HTTP/WS header, and the full
chat→sim→telemetry→Firebase demo still passes.

## 11.5 Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Blueprint child classes reference moved C++ classes by path | Use `ue-cpp-refactor` rename with CoreRedirects; keep `UCLASS` names stable, only move files |
| Map/GameMode still points at template `VCOREGameMode` | Verify in `Config/DefaultEngine.ini` + `.umap` before deleting (P0 gate) |
| Off-thread crashes when splitting HTTP handlers | Preserve rule: handlers parse JSON off-thread, all state mutation on game thread |
| Telemetry transport regression | Keep `ws` default; re-verify Firebase `cells/cell_demo` writes after P3 |

## 11.6 Acceptance Checklist

- [ ] P0: template/variant files removed, `Build.cs` cleaned, editor builds
- [ ] P1: feature folders in place, PIE smoke passes
- [ ] P2: `KPIAccumulator` extracted, KPI report unchanged
- [ ] P3: `Net/` boundary extracted, domain has zero network includes
- [ ] P4: `CameraDirector` extracted, lint clean, end-to-end demo green

---

# Part 12 — Portfolio Feature Extensions

Net-new features built to showcase the portfolio capabilities (UE digital-twin virtual process,
real-time data-driven visualization, 3D graphics/rendering, AI-agent scenario design & verification).
Full design, interaction scenarios, and showcase narrative live in
**[spec_portfolio_features.md](spec_portfolio_features.md)**. Summary of the new C++ units:

| Feature | Class | `public/` · `private/` subdir | Capability showcased |
|---|---|---|---|
| Congestion heatmap | `UCongestionHeatmapComponent` | `visualization/` | Real-time data-driven 3D viz, dynamic materials |
| Live status billboards | `UAGVStatusBillboardComponent` | `visualization/` | Data-driven world-space rendering |
| Cinematic event director | `UCinematicEventDirector` | `cinematics/` | 3D camera/rendering, evaluator presentation |
| Scenario verification | `UScenarioVerificationComponent` | `scenario/` | AI-agent scenario design & verification |
| Sim status HUD | web `VcoreHud` (fed by the process telemetry frame) | `chat-web/` | Status/event/verdict overlay, migrated out of UE5 (Part 7) |

These classes are self-contained domain/presentation units with no `Net/` dependency; intended wiring
into `AGVSimController` (or its future `Simulation/` orchestrator) is documented per-feature in
[spec_portfolio_features.md](spec_portfolio_features.md).
