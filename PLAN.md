# PLAN.md - VCORE Project Implementation Plan

> **Rule:** Read this before every task. Mark tasks `[x]` immediately upon completion.
> Completed work is summarized in [DONE.md](DONE.md).
> **Current Phase:** Phase 6/7 — Virtual Process + Telemetry stabilization
> **Last reorganized:** 2026-06-12 (added P6 — production-grade UE5 refactor / Phase 10 for portfolio).

---

## Critical Path

**2026-06-09: the live-loop blocker is cleared.** The full sim loop is verified end-to-end against
a `-game` standalone with UE HTTP `:7777` reachable (see P1 / [DONE.md](DONE.md)). What remains is
**editor-only** asset wiring — zone camera tags, GameMode confirmation, and the Phase 9 F1/F2/F3
material + camera tuning — none of which is doable from standalone; they need an in-editor pass.
Treat that in-editor pass as the prerequisite for the rest of P2/P3.

| Phase 9 | Portfolio feature extensions | F1/F2/F3 wiring + tuning open |
| Phase 10 | Production-grade UE5 refactor (portfolio) | New — see P6 |


---

## P6 — Production-grade UE5 process simulation refactor (Phase 10, portfolio)

> **Goal:** Elevate the UE5 subsystem from a demo prototype to a production-grade, portfolio-quality
> codebase — event-driven, component-partitioned (Lyra-style), with clear class responsibilities and
> zero "demonstrative" fakery. Supersedes/absorbs the remaining Phase 8 decomposition (P5) where they
> overlap. Each step must keep the demo compiling and the live loop (P1) green.
>
> **Driver context:** the current AGV behavior has demo shortcuts — stations are passive (no
> collision/trigger; AGV drives through them), pickup/dropoff fire at hardcoded spline ratios
> (`0.22`/`0.72`) unrelated to placed `StationActor`s, battery is faked, and several actors are
> vestigial (`ALoadingDockActor::AssignNextTask` is dead code; `EStationKind`/`Capacity`/
> `CapabilityTags`/`ZoneId` are authored but never read). See the "Demo-like elements" note below.

### P6.0 — Architecture design (do first; gates the rest) ✅ done 2026-06-12 → [docs/spec_p6_refactor.md](docs/spec_p6_refactor.md)
- [x] **Audit the class list requiring modification** and record current vs. target responsibility
      for each. Candidates already identified:
      - `AAGVActor` (~890 lines) — God-actor mixing movement, the `EAGVState` machine, traffic
        reservation, nameplate widget, chase camera, and task plumbing. **Decompose.**
      - `AAGVSimController` (~1600 lines) — config + HTTP `:7777` + WS + telemetry transports + sim
        lifecycle + chat ingest + camera. (Already Phase 8 P3/P4 / P5 here.)
      - `AStationActor` — passive anchor; needs a real interaction volume + station-kind behavior.
      - `ADispatcherActor` — command-path only; ignores station kind/capability. Make it the single
        assignment authority for both autonomous and commanded flows.
      - `ALoadingDockActor` — vestigial; `AssignNextTask` dead. Either make it a real dock with a
        docking pose/queue or remove it.
      - `ATrafficManagerActor` / `AIntersectionManager` — overlapping reservation responsibilities;
        collapse to one boundary.
      - `UAGVTaskComponent` + `AGVStateTree*` tasks — `EAGVState` (in `AGVActor`) and the StateTree
        lifecycle duplicate state; pick one source of truth.
      - Components: `USplinePathComponent`, `UAGVStatusBillboardComponent`, `UCongestionHeatmapComponent`,
        `UKPIAccumulator`.
- [x] **Propose the new directory structure + class architecture** (component-first, Lyra-derived).
      Candidate layout to evaluate:
      ```
      Source/VCORE/
        Core/        ← GameMode, SimSubsystem (lifecycle), config
        AGV/         ← AAGVActor (thin pawn) + UAGVMovementComponent,
                       UAGVTaskRunnerComponent, UAGVStateComponent
        Stations/    ← AStationActor + UStationInteractionComponent (trigger), station-kind strategies
        Dispatch/    ← ADispatcherActor (sole assignment authority)
        Traffic/     ← unified reservation boundary (Traffic+Intersection merged)
        Telemetry/   ← Net boundary: SimNetworkComponent, SimEventDispatcher, TelemetryEmitter, SimJson
        Camera/      ← CameraDirector
        KPI/ Viz/    ← UKPIAccumulator, heatmap, billboards
      ```
- [x] **Define the event-driven contract** — replace per-Tick polling / direct calls with delegates
      or a `GameplayMessageSubsystem`-style bus for: state changes, station arrival, reservation
      grant/release, task complete/fail, collision. Document the events before refactoring.
      → `USimEventBus` (PIE-scoped `UWorldSubsystem`) + local delegates; event catalog in §3 of the design doc.

> **P6.0 decisions locked 2026-06-12 (design doc §5):** battery → ~~remove~~ **reversed: keep the
> existing fake battery** (restored after P6.1d — a battery readout is needed for the demo); StateTree
> runtime → **retire** (`UAGVTaskComponent` lifecycle is sole control path, `EAGVState` deleted);
> LoadingDock → **delete & subsume** into stations. P6.1 proceeds on these.

### P6.1 — Remove demo/legacy code & de-fake behavior
- [x] **Station interaction** (P6.1a bus + P6.1b trigger) — `AStationActor` now owns a
      `UStationInteractionComponent` trigger volume; an AGV arriving by proximity drives Load/Unload off
      `EStationKind` (Pickup/Dropoff). Removed the hardcoded `PickupDistanceRatio`/`DropoffDistanceRatio`
      checkpoints. Controller seeds a Pickup+Dropoff pair per path if none authored (loop stays green);
      `StationArrived` published on the bus. Charger/Inspection kinds carry no action yet (Charger N/A —
      battery removed in P6.1d).
- [x] **Battery model — decision reversed 2026-06-12: keep the existing fake battery.** P6.1d had
      removed it, but a battery readout is needed for the demo, so the fake model was **restored**:
      `BatteryPercent` drains a flat `0.15/s` (floored at 20%, reset to 100% on configure), surfaced via
      the dispatcher `BatteryScore`, F2 billboard, `AGV_STATE_CHANGE` event + telemetry JSON, and the web
      `BatteryBar` gauge. Still fake (no real charge/discharge or `Charger` station) — revisit only if a
      real model is wanted later.
- [x] **Delete dead/vestigial paths** (P6.1c CreateFallbackStation + P6.1d) — removed `ALoadingDockActor`
      entirely (subsumed by stations; task counting already lives in `UKPIAccumulator`),
      `CreateFallbackStation` (P6.1c), and moved the `BaseMoveSpeed`/`ActionDurationSeconds` `// TODO: config`
      hardcodes to `EditAnywhere` UPROPERTYs on `AAGVActor` (editor-authored config).
- [x] **Make station metadata meaningful** (P6.1c) — `Capacity` gates dispatcher eligibility
      (`Capacity>0`) and scores throughput; `CapabilityTags` breadth and a configured `ZoneId` are
      tie-breaking fit signals folded into `StationScore` + the dispatch explanation. The autonomous
      loop now routes through `ADispatcherActor::SelectStationForAgv` (no more direct
      `AssignDeliveryTask(nullptr)` bypass) — the dispatcher is the sole assignment authority.

### P6.2 — Decompose & optimize
- [ ] **Split `AAGVActor`** into a thin pawn + components (movement, state, task-runner) per the
      P6.0 layout. Target: no single class owning movement + state + traffic + UI + camera.
- [ ] **Finish `AAGVSimController` decomposition** (folds in Phase 8 P3/P4 / P5): extract the `Net/`
      boundary (`SimNetworkComponent`, `SimEventDispatcher`, `TelemetryEmitter`, `SimJson`) and
      `CameraDirector`.
- [ ] **Apply component/ECS-style patterns** for the per-AGV hot path; convert remaining Tick polling
      to the event bus from P6.0.

### P6.3 — Documentation & quality gate
- [ ] **Comment every function in every public header** — a clear one-line purpose (and non-obvious
      `why`) on each declaration across `Source/VCORE/Public/**`.
- [ ] **Update specs** — [docs/spec_unreal.md](docs/spec_unreal.md) Part 11 (architecture) to reflect
      the new directory/class structure before landing the code.
- [ ] **Quality gate** — `ue-architecture-lint` + `ue-perf-lint` run clean; demo loop (P1) still
      green end-to-end after the refactor.

---

## Backlog / Lower priority

- [ ] Redis pub/sub for backend WebSocket fan-out (only needed if >1 concurrent frontend client).
- [ ] UE5 time-acceleration mode (1 sec = N simulated minutes, configurable).

---

## Editor Setup Required (post-code-change)

- **`AuthoredAgvs` wiring (now optional — auto-discovered).** `AuthoredAgvs` and `AuthoredPaths`
  are independent arrays and a unit needs an entry in both, so the cell's max AGV count is
  `min(AGV actors in the level, AuthoredPaths)`. As of 2026-06-13 `InitializeRuntimeSimulationActors`
  auto-discovers any level-placed `AGVActor` not already in `AuthoredAgvs` (name-sorted) up to the
  path count, so **placing N AGV actors + N paths in the level is enough** — you no longer have to
  hand-wire `AuthoredAgvs`. To run 5 AGVs, place 5 `AGVActor` instances and assign 5 `AuthoredPaths`.
  You may still hand-assign `AuthoredAgvs` if you need a specific `AuthoredAgvs[i]`↔`AuthoredPaths[i]`
  pairing. Remove any references to the now-unused `AGVActorClass`.
- **Collision detection radius** — `CollisionDetectionRadius` (default 300 cm) is editable on the
  controller. Increase if AGVs still pass through each other; decrease to require closer proximity.
- **Collision-halt termination (2026-06-14) — needs an editor build.** `AGVSimController` now ends a
  run when every spawned AGV is `STOPPED_COLLISION` (`AllSpawnedAgvsCollisionStopped()` → existing
  `CompleteRuntimeRun("collision_halt")`), so the chatbot reports the collision and final KPIs. The
  backend half (collision-halt report notice, internal-only `move_to_station`, live
  `simulation_status` route) is done and `pytest`-green; the UE5 C++ half is **build-deferred**
  (Perforce read-only cleared on `AGVSimController.{h,cpp}`; reconcile + compile in the editor, then
  verify by driving all AGVs into a mutual collision in PIE). See [DONE.md](DONE.md) 2026-06-14.

---

## Discovered Issues / Notes

- **Phase 2 reconciliation (action: confirm in PIE, then close).** The original Phase 2 checklist
  is stale — most of it is either already built or superseded by later architecture:
  - 2.1 AGV cell (3 AGVs, spline paths, intersection, dock): built in the "First real UE5 AGV
    runtime loop" (see [DONE.md](DONE.md) Phase 1 infra). **Verify in P1 PIE, then mark done.**
  - 2.2 Collision detection: built. Bottleneck detection emitter exists (`EmitBottleneckEvent`).
    `timeline_logs` WebSocket logging was part of the **old web stack and is gone** — re-scope to
    the current SSE/telemetry pipeline, do not restore `timeline_logs`.
  - 2.3 UE5 in-viewport HUD: **superseded** — F5 HUD migrated to the web `VcoreHud` component.
    Drop this item.
  - 2.4 Backend KPI calculation: **superseded** — KPIs now computed in-engine by `UKPIAccumulator`
    (Phase 8 P2). The old `kpi_results` table belonged to the dropped web stack. Drop this item.
  - **TODO:** after P1 PIE, fold the surviving 2.1/2.2 items into "verified" and delete the rest.

- **`AGVSimController` God Class** (~1600 lines) — tracked as Phase 8 P3/P4 above. Still owns
  config + HTTP server + WS + telemetry transports + sim lifecycle + chat ingest + camera even
  after the `UKPIAccumulator` extraction. Net/Camera extraction (P5) is the main remaining
  separation-of-responsibility work.

- **Known platform constraint:** UE5 raw-socket UDP/TCP to the Dockerized collector fails on this
  Windows host (Docker Desktop proxy drops bytes silently). Telemetry default is `ws` transport —
  do not regress to raw sockets. (See [DONE.md](DONE.md) Known Constraints.)

- **Demo-like elements in current AGV behavior (drives P6).** Source review 2026-06-12:
  - `AStationActor` is fully passive (`bCanEverTick=false`, no collision primitive). The AGV's only
    overlap handler reacts to *other AGVs* — so an AGV physically drives through a placed station with
    no state change. Stations are only reachable by `StationId` via chat command (`DirectToStation`),
    never by proximity.
  - Autonomous Load/Unload fires at hardcoded spline ratios `PickupDistanceRatio=0.22` /
    `DropoffDistanceRatio=0.72`, unrelated to placed station positions. `EStationKind` (Pickup/Dropoff/
    Charger/Inspection) and `Capacity`/`CapabilityTags`/`ZoneId` are authored but never read.
  - Battery is faked: flat `0.15/s` drain, floored at 20%, reset to 100 on configure, never recharges;
    `Charger` kind unused.
  - `ADispatcherActor` is consulted only on the command path; the autonomous loop calls
    `AssignDeliveryTask(nullptr)` directly. `ALoadingDockActor::AssignNextTask` is dead code (only
    `CompleteTask`, a counter, is live). `CreateFallbackStation` invents a station on the spline if a
    commanded `StationId` isn't found. Commanded moves set `bCarryingLoad=true` immediately and skip a
    real pickup step.
