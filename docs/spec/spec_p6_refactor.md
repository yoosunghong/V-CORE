# P6 — Production-grade UE5 Process-Simulation Refactor (Phase 10) — Architecture Design

> **Status:** P6.0 design (this document). Gates P6.1–P6.3.
> **Scope:** the `Source/VCORE` AGV-cell simulation. Supersedes/absorbs the remaining Phase 8
> decomposition recorded in [spec_unreal.md](spec_unreal.md) Part 11 (the `AGVSimController` Net/Camera
> split) and extends it to the **AGV actor, stations, dispatch, and traffic**.
> **Constraint:** every step must keep the demo compiling and the P1 live loop green. Class `UCLASS`
> names stay stable (CoreRedirects for any rename); only files move and responsibilities shift.
> When the code lands, the relevant parts of this doc fold into Part 11 (P6.3).

This is the design output of **PLAN.md → P6.0**. Three deliverables:

1. [§1 Class audit](#1-class-audit--current-vs-target-responsibility) — current vs. target responsibility.
2. [§2 Target architecture](#2-target-architecture--directories--classes) — directory + class layout.
3. [§3 Event-driven contract](#3-event-driven-contract) — the events that replace Tick-polling / direct calls.

---

## 1. Class audit — current vs. target responsibility

Line counts from the 2026-06-12 source review. "Demo-fakery" column flags behavior that P6.1 must
de-fake.

| Class | Lines (cpp/h) | Current responsibility (what it actually owns today) | Target responsibility | Demo-fakery to remove |
|---|---|---|---|---|
| **`AAGVActor`** | 778 / 179 | **God-actor.** Procedural spline movement (`UpdateMovement`, `UpdateTransformFromDistance`, `GetVelocity` override); the `EAGVState` machine (`TransitionTo`, `HandleCheckpointTransitions`); traffic reservation calls; **fake battery** (`BatteryPercent`); chase camera (`CameraBoom`+`ViewpointCamera`); nameplate widget (`NameplateWidgetComponent`, `InitializeNameplateWidget`/`UpdateNameplateWidget`/`FaceNameplateToCamera`); task plumbing (`CurrentOrder`, `AssignDeliveryTask`, `DirectToStation`); per-AGV KPI counters (`CompletedTasks`, `ActiveTimeSeconds`). | **Thin `APawn`.** Owns identity + composition only; delegates movement, state, and task-running to components. No camera/UI/traffic/battery logic in the actor body. | Hardcoded `PickupDistanceRatio=0.22`/`DropoffDistanceRatio=0.72` checkpoints; `BaseMoveSpeed`/`ActionDurationSeconds` `// TODO: config`; flat `BatteryPercent` drain. |
| **`AAGVSimController`** | 2283 / 268 | Config load; 8-route HTTP server `:7777`; WS client; 3 telemetry transports (UDP/TCP/WS); demo-fallback + progress + auto-complete timers; runtime sim lifecycle; chat-correlated event ingest/echo; camera (`SelectViewTarget`/`FindZoneCamera`); station registry; order bookkeeping. | **Application orchestrator only** — run lifecycle + command routing. IO, telemetry, camera, and JSON extracted (Part 11 P3/P4). | `CreateFallbackStation` (invents a station on the spline); autonomous loop calls `AssignDeliveryTask(nullptr)` directly (`:1161`,`:1290`), bypassing the dispatcher. |
| **`AStationActor`** | 34 / 54 | **Fully passive** (`bCanEverTick=false`, no collision primitive). Has `StationId`, `StationKind`, `Capacity`, `ZoneId`, `CapabilityTags`, `DockingPose`, reservation (`ReserveForAgv`/`ReleaseReservation`). Reachable only by `StationId` via chat command — an AGV physically drives *through* it. | **Active interaction anchor.** Owns a trigger volume (`UStationInteractionComponent`) that fires Load/Unload by AGV proximity, driven by `EStationKind`. `Capacity`/`CapabilityTags`/`ZoneId` feed dispatch eligibility. | The metadata fields are authored but **never read** today. |
| **`ADispatcherActor`** | 86 / 52 | AGV scoring (`SelectAgvForStation`, `ScoreAgvForStation`, `FDispatchScoreBreakdown`). Consulted **only on the command path** (`:1899`). | **Sole assignment authority** for *both* autonomous and commanded flows. Scoring reads station kind/capability/capacity. | Autonomous flow bypasses it entirely. |
| **`ALoadingDockActor`** | 22 / 19 | **Vestigial.** `AssignNextTask` is dead code (defined, never called externally). Only `CompleteTask` (a counter) is live. | **Decision: remove.** The dock's docking-pose/queue role is subsumed by `AStationActor` (Pickup/Dropoff kinds with `DockingPose`). The completed-task counter moves to `UKPIAccumulator`. | Entire `AssignNextTask` path. |
| **`ATrafficManagerActor`** | 188 / 54 | Segment reservation: `RequestReservation`/`ReleaseReservation`, queue+wait+`ActiveAgv` per `FTrafficSegment`. | **The single reservation boundary** (merge target). | — |
| **`AIntersectionManager`** | 97 / 30 | **Overlapping** single-intersection reservation: `RequestEntry`/`ReleaseEntry`, queue+wait+`ActiveAgv`. `AGVActor` uses Traffic if present *else* Intersection (`AGVActor.cpp:548-549`). | **Decision: collapse into `ATrafficManagerActor`.** Intersection becomes the default segment (it already is — `INTERSECTION_X`). Remove `AIntersectionManager`; KPI wait-time reads move to the traffic manager. | Two classes implementing the same queue. |
| **`UAGVTaskComponent`** | 256 / 102 | StateTree-ready lifecycle facade: `EAGVTaskLifecycleState` (12 states), `OnLifecycleChanged` delegate, StateTree dispatch. | **The single source of task/lifecycle truth** (state component). | Duplicates `EAGVState` (8 states) held in `AAGVActor`. |
| **`AGVStateTree*` tasks** (8) | ~150 total | StateTree task nodes (Reserve/Move/Wait/Load/Unload/Complete/Fail). | Keep as the StateTree execution layer **iff** StateTree is chosen as the runtime; otherwise retire. See §2 decision. | — |
| **`USplinePathComponent`** | 27 / 15 | Closed-loop spline math (wrapped location/rotation/length). | Keep as-is (clean domain helper). | — |
| **`UAGVStatusBillboardComponent`** | 108 / 43 | F2 world-space status label. | Keep; becomes a pure subscriber to the AGV event bus (§3) instead of polling getters each tick. | Per-tick getter polling. |
| **`UCongestionHeatmapComponent`** | 285 / 109 | F1 data-driven heatmap. | Keep; fed by telemetry frame (already largely event/timer-driven). | — |
| **`UKPIAccumulator`** | 79 / 52 | Counters + report build (already extracted, Phase 8 P2). | Keep; absorbs the dock's task counter and traffic wait metrics. | — |

### Two source-of-truth conflicts to resolve in P6.0 (decided here)

- **State machine duplication** — `EAGVState` (in `AAGVActor`) vs. `EAGVTaskLifecycleState` (in
  `UAGVTaskComponent`). **Decision:** `UAGVTaskComponent`'s lifecycle is the **single source of
  truth** for *task/order* state; the AGV keeps only a minimal *motion* sub-state
  (`Idle/Driving/Blocked`) in a new `UAGVMovementComponent`, which it derives from the lifecycle, not
  the reverse. `EAGVState` is deleted.
- **StateTree vs. hand-rolled machine** — the StateTree component + 8 task nodes and the in-actor
  `EAGVState` switch both try to drive the AGV. **Decision for the demo:** keep **one** runtime —
  the component-driven lifecycle (`UAGVTaskComponent` + `UAGVTaskRunnerComponent`) — because it is
  already what the live loop exercises. The `AGVStateTree*` nodes and `UStateTreeComponent` wiring
  are **retired** (moved out of the build) unless a later phase explicitly re-adopts StateTree as the
  authoring surface. This removes the dead second control path flagged in PLAN.

---

## 2. Target architecture — directories & classes

### 2.1 Convention (keep the existing `public/` + `private/` split)

The PLAN.md candidate sketch (`Core/`, `AGV/`, `Stations/`, …) reads as a flat tree, but the
**authoritative module convention** (spec_unreal.md §11.3) is the Unreal `public/` (headers) +
`private/` (cpp) split with **purpose subdirectories mirrored under each**, and `public/*` subdirs
registered in `VCORE.Build.cs` `PublicIncludePaths`. **Decision:** keep that convention and realize
the PLAN's component-first grouping as purpose subdirs — do **not** flatten. This preserves bare-name
includes and the enforced Net/Domain layering rule.

### 2.2 Target layout (component-first, Lyra-derived)

```
Source/VCORE/
├── public/                                    private/  (matching .cpp under same subdir)
│   ├── core/        VirtualProcessGameMode.h          ← framework glue (HUD is web-side)
│   │                SimSubsystem.h                     ← NEW: run-lifecycle UWorldSubsystem (optional, see 2.4)
│   ├── controller/  AGVSimController.h                 ← APPLICATION orchestrator (thin, Part 11 P3/P4)
│   ├── agv/         AGVActor.h                         ← thin APawn
│   │                AGVMovementComponent.h             ← NEW: spline follow + GetVelocity + motion sub-state
│   │                AGVTaskComponent.h                 ← MOVED from component/: lifecycle = task source of truth
│   │                AGVTaskRunnerComponent.h           ← NEW: executes the lifecycle (load/unload/move steps)
│   ├── stations/    StationActor.h                     ← active anchor
│   │                StationInteractionComponent.h      ← NEW: trigger volume + EStationKind behavior
│   ├── dispatch/    DispatcherActor.h                  ← sole assignment authority
│   ├── traffic/     TrafficManagerActor.h              ← unified reservation (Intersection merged in)
│   ├── path/        SplinePathComponent.h, AGVPathActor.h
│   ├── metrics/     KPIAccumulator.h
│   ├── visualization/ CongestionHeatmapComponent.h, AGVStatusBillboardComponent.h
│   ├── cinematics/  CinematicEventDirector.h
│   ├── scenario/    ScenarioVerificationComponent.h
│   ├── domain/      TransportOrder.h, LoadObject.h
│   ├── events/      SimEventBus.h, SimEventTypes.h      ← NEW: §3 event contract
│   └── net/         SimNetworkComponent.h, SimEventDispatcher.h, SimJson.h,
│                    telemetry/TelemetryEmitter.h        ← BOUNDARY (Part 11 P3)
```

**Deltas vs. today**
- **New:** `agv/AGVMovementComponent`, `agv/AGVTaskRunnerComponent`, `stations/StationInteractionComponent`,
  `events/SimEventBus` (+ `SimEventTypes`). Optional `core/SimSubsystem`.
- **Moved:** `AGVTaskComponent` → `agv/`; `DispatcherActor` → `dispatch/`; `TrafficManagerActor` → `traffic/`;
  `SplinePathComponent`/`AGVPathActor` → `path/`; `TransportOrder`/`LoadObject` → `domain/`.
- **Removed:** `AIntersectionManager` (merged into traffic), `ALoadingDockActor` (subsumed by stations),
  the `EAGVState` enum, and the `AGVStateTree*` task set + `UStateTreeComponent` wiring (retired runtime).
- **Net boundary** (`SimNetworkComponent`, `SimEventDispatcher`, `TelemetryEmitter`, `SimJson`,
  `CameraDirector`) is the Part 11 P3/P4 work, folded in here.

### 2.3 `AAGVActor` decomposition (the headline split)

| Concern | Today (in `AAGVActor`) | Target owner |
|---|---|---|
| Spline movement, `GetVelocity`, speed/motion sub-state | `UpdateMovement`, `UpdateTransformFromDistance`, `CurrentSpeed`, `BaseMoveSpeed` | **`UAGVMovementComponent`** |
| Task/order lifecycle | `EAGVState`, `TransitionTo`, `CurrentOrder`, `AssignDeliveryTask`, `DirectToStation` | **`UAGVTaskComponent`** (state) + **`UAGVTaskRunnerComponent`** (execution) |
| Traffic reservation requests | `ShouldRequestTrafficSegment`, `RequestReservation`/`RequestEntry` calls | `UAGVMovementComponent` asks, **`ATrafficManagerActor`** decides |
| Battery | `BatteryPercent` (fake) | Removed, or real model tied to `Charger` stations (P6.1 decision below) |
| Chase camera | `CameraBoom` + `ViewpointCamera` | Kept on the pawn (it *is* a per-pawn viewpoint) but driven by `UCameraDirector` |
| Nameplate / status label | `NameplateWidgetComponent` + face-camera logic | `UAGVStatusBillboardComponent` (already exists; subscribe via §3) |
| Per-AGV KPI counters | `CompletedTasks`, `ActiveTimeSeconds` | Reported via events into `UKPIAccumulator` |

Result: `AAGVActor` becomes identity + component composition + a thin façade of `BlueprintPure`
getters the AnimBP/web already call. No single class owns movement + state + traffic + UI + camera.

### 2.4 Battery decision (P6.1)

**Recommendation: remove the field.** A real charge/discharge model only earns its place if a
`Charger` station and a charge behavior exist; that is net-new scope with no demo consumer today. The
honest, non-fake option for the demo is to **delete `BatteryPercent`** and the `BatteryScore`
dispatch term until a charging behavior is actually built. (If a stakeholder wants the gauge on the
HUD, the fallback is a real model gated on `EStationKind::Charger` — documented but not default.)

### 2.5 `SimSubsystem` (optional)

A `UWorldSubsystem` owning pure run-lifecycle state (running/paused/speed/elapsed) would let the
controller shrink further and give components a Tick-free clock source. **Marked optional** — adopt
only if `AGVSimController` is still > ~400 lines after the Part 11 Net/Camera extraction; otherwise it
is premature abstraction for demo scale.

---

## 3. Event-driven contract

**Goal (PLAN P6.0):** replace per-Tick polling and cross-actor direct calls with delegates / a
message bus, so producers don't reach into consumers. Two tiers:

### 3.1 Local (intra-actor) — typed dynamic multicast delegates

Already partly present (`UAGVTaskComponent::OnLifecycleChanged`). Standardize on
`DECLARE_DYNAMIC_MULTICAST_DELEGATE_*` exposed on the owning component, so same-actor consumers (e.g.
the status billboard) subscribe instead of polling getters each tick:

| Delegate (on) | Signature | Replaces |
|---|---|---|
| `OnLifecycleChanged` (`UAGVTaskComponent`) | `(Prev, New: EAGVTaskLifecycleState, Reason)` | *(exists)* the `EAGVState` switch |
| `OnMotionChanged` (`UAGVMovementComponent`) | `(bMoving: bool, Speed: float)` | billboard/AnimBP polling `IsMoving()`/`GetCurrentSpeed()` each tick |

### 3.2 Sim-wide (cross-actor) — a `USimEventBus` (GameplayMessage-style)

A single lightweight relay (a `UGameInstanceSubsystem` or a `UObject` owned by the controller —
**recommend `UWorldSubsystem`** so it is PIE-scoped and auto-reset per run). Producers `Broadcast`;
the controller / KPI / cinematics / telemetry subscribe once. This is the
`GameplayMessageSubsystem`-style bus PLAN calls for, kept minimal (typed delegates, no tag routing
needed at demo scale).

**Event catalog** (`events/SimEventTypes.h`) — each is a small `USTRUCT` payload:

| Event | Payload | Producer | Subscribers | Replaces today's |
|---|---|---|---|---|
| `AgvStateChanged` | agvId, from, to, speed | `UAGVTaskComponent` | controller (chat echo), telemetry | `EmitAgvStateChange` direct call |
| `StationArrived` | agvId, stationId, kind | `UStationInteractionComponent` (overlap) | dispatcher, task-runner, controller | hardcoded spline-ratio checkpoints |
| `ReservationGranted` / `ReservationReleased` | agvId, segmentId, waitSec | `ATrafficManagerActor` | KPI (wait metrics), cinematics | direct `RequestEntry` bool return |
| `TaskCompleted` / `TaskFailed` | agvId, orderId, reason | `UAGVTaskRunnerComponent` | KPI, dispatcher (free the AGV), controller | `NotifyTaskCompleted` direct call, dock counter |
| `CollisionDetected` | agvIdA, agvIdB, pos, relVel | `AAGVActor::OnOverlapBegin` | KPI, cinematics (camera-to-hotspot), controller | `NotifyCollision` direct call |
| `BottleneckDetected` | agvId, sectionId, waitSec, queued[] | `ATrafficManagerActor` | cinematics, telemetry | `EmitBottleneckEvent` direct call |

**Rule:** domain producers `Broadcast` to the bus and never hold a `Net/` reference. The controller is
the only subscriber that bridges bus → backend (`SimEventDispatcher`), preserving the Part 11
Net/Domain layering. Subscriptions are bound in `BeginPlay`/`Configure` and unbound in `EndPlay`
(matching the existing PIE-restart discipline that prevents stale callbacks).

### 3.3 What stays on Tick

Tick is still legitimate for **continuous** work: spline advancement (`UAGVMovementComponent`),
heatmap accumulation, and the telemetry frame timer (5 Hz). The contract removes Tick *polling of
discrete state* (arrival, state change, completion) — those become events.

---

## 4. Migration order (P6.1 → P6.3) — each step compiles & keeps P1 green

1. **P6.1a** ✅ **done 2026-06-12.** Added `events/SimEventBus` (`UWorldSubsystem`) + `SimEventTypes`;
   routed the four existing `Emit*`/`Notify*` direct calls (AgvStateChanged, TaskCompleted, Collision,
   Bottleneck) through the bus. Producers `Broadcast*`; the controller subscribes in `BeginPlay` /
   unsubscribes in `EndPlay`. Pure indirection — no behavior change. (StationArrived + reservation
   events deferred to P6.1b/P6.2 when their producers exist.)
2. **P6.1b** ✅ **done 2026-06-12.** Added `UStationInteractionComponent` (a `USphereComponent`
   trigger, in `Component/`); `AStationActor` attaches one. On AGV overlap it broadcasts
   `StationArrived` and calls `AAGVActor::HandleStationArrival`, which drives Load/Unload off
   `EStationKind` (strict Pickup/Dropoff match). Removed `PickupDistanceRatio`/`DropoffDistanceRatio`
   and their checkpoint branches (the commanded `MovingToStation` docking checkpoint stays). The
   controller's `EnsureInteractionStations()` seeds a Pickup+Dropoff pair per path at 0.22/0.72 when
   the level authors neither kind, so the loop stays green pre-authoring; seeded stations are tagged
   `RuntimeInteractionStation` and torn down with the run. **Known limit:** overlap detection can tunnel
   at very high sim-speed multipliers (trigger radius 250 cm); fine at demo speeds.
3. **P6.1c** ✅ **done 2026-06-12.** `DispatchIdleAgvs` now routes every autonomous assignment through
   the dispatcher: it gathers Pickup stations and calls the new `ADispatcherActor::SelectStationForAgv`
   (AGV-centric selection) — an idle AGV is only assigned when an eligible Pickup station exists, so
   the direct `AssignDeliveryTask(nullptr)` bypass is gone (a degraded no-dispatcher fallback remains).
   `ScoreAgvForStation` now gates eligibility on `Capacity > 0` and folds Capacity (throughput),
   `CapabilityTags` breadth, and a configured `ZoneId` into `StationScore` + the explanation string.
   `CreateFallbackStation` removed (its only caller, the empty-registry seeding, is covered by
   `EnsureInteractionStations`); teardown now tracks only `RuntimeInteractionStation`. **Demo-scope
   note:** capacity is an eligibility gate (single-slot reservation, not N-occupancy) and
   capability/zone are tie-breaker signals, not a full matching subsystem.
4. **P6.1d** ✅ **done 2026-06-12.** Deleted `ALoadingDockActor` (files + all references; its task
   counter was redundant with `UKPIAccumulator`). Moved the `BaseMoveSpeed`/`ActionDurationSeconds`
   `// TODO: config` hardcodes to `EditAnywhere` UPROPERTYs on `AAGVActor`. **Battery:** originally
   removed in this step, then **restored 2026-06-12** by request — the fake flat-drain model is kept end
   to end (AGV field/drain/reset, dispatcher `BatteryScore`, F2 billboard, `AGV_STATE_CHANGE` event +
   telemetry JSON, web `BatteryBar`). Net P6.1d = LoadingDock removed + config lifted; battery unchanged
   from pre-P6.1d.
5. **P6.2a** Merge `AIntersectionManager` into `ATrafficManagerActor`; delete the former.
6. **P6.2b** Split `AAGVActor` into pawn + `UAGVMovementComponent` + `UAGVTaskRunnerComponent`; delete
   `EAGVState`; retire `AGVStateTree*` + `UStateTreeComponent`.
7. **P6.2c** Finish the Part 11 P3/P4 Net/Camera extraction on `AGVSimController`.
8. **P6.3** Comment every public-header declaration; fold this design into spec_unreal.md Part 11;
   run `ue-architecture-lint` + `ue-perf-lint`; re-verify the live loop.

---

## 5. Decisions (locked 2026-06-12)

Signed off by the user — these are now binding for P6.1:

- **Battery:** ~~Remove the field~~ → **reversed 2026-06-12: keep the existing fake battery.** P6.1d
  removed it, but a battery readout is needed for the demo, so the flat-drain model was restored
  (`BatteryPercent`, `BatteryScore`, billboard/event/telemetry/web gauge). Still fake — no `Charger`
  behavior; revisit only if a real charge/discharge model is wanted.
- **StateTree:** ✅ **Retire the `AGVStateTree*` runtime** + `UStateTreeComponent` wiring. The
  component-driven `UAGVTaskComponent` lifecycle is the sole control path; `EAGVState` is deleted.
- **`LoadingDock`:** ✅ **Delete and subsume** into `AStationActor` (Pickup/Dropoff kinds); the
  task counter moves to `UKPIAccumulator`.
