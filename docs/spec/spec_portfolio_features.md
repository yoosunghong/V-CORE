# UE5 Portfolio Feature Extensions

**Project:** VCORE — AI Twin Platform for Pre-verification of Industrial Operational Strategies
**Subsystem:** Unreal Engine 5 (`Source/VCORE`)
**Status:** F1–F4 wired into `AGVSimController`; **F4 + F5 HUD code-complete** (2026-06-07). F1/F3
editor tuning remains. See [guide_unreal_editor_f4_hud.md](guide_unreal_editor_f4_hud.md).
**Parent spec:** [spec_unreal.md](spec_unreal.md) (canonical UE5 spec; this is its Part 12 detail)

> **Why this doc exists.** The core AGV digital-twin demo already runs end-to-end
> (chat → sim → telemetry → Firebase dashboard). This document specs a set of *portfolio-facing*
> Unreal features chosen to demonstrate, on top of that demo, four target competencies:
>
> 1. **Unreal Engine digital-twin virtual process** — the AGV cell is the twin; these features make
>    the twin *legible* and *self-verifying*.
> 2. **Real-time data-driven visualization** — every visual below is driven live by simulation state
>    (AGV positions, KPIs, sim events), not authored animation.
> 3. **3D graphics & rendering** — dynamic materials / material parameter collections, spline-mesh
>    ribbons, world-space text, cinematic camera blends.
> 4. **AI-agent process scenario design & verification** — the agent does not just *start* a run; it
>    attaches *acceptance criteria* and the engine reports a machine-readable **pass/fail verdict**.
>
> Each feature is a self-contained C++ unit placed under the module's `public/` (header) + `private/`
> (cpp) split, in a purpose subdirectory (see the directory map in [spec_unreal.md](spec_unreal.md)
> Part 11.3). None depend on the network boundary; they consume domain state and are driven by the
> orchestrator.

---

## 1. Feature Overview

| # | Feature | Class | `public/`·`private/` subdir | Primary capability | Drives |
|---|---|---|---|---|---|
| F1 | **Congestion Heatmap** | `UCongestionHeatmapComponent` | `visualization/` | Real-time data-driven 3D viz | Floor decal / MPC density colouring |
| F2 | **Live Status Billboards** | `UAGVStatusBillboardComponent` | `visualization/` | Data-driven world-space rendering | Per-AGV floating text (state/battery/speed) |
| F3 | **Cinematic Event Director** | `UCinematicEventDirector` | `cinematics/` | 3D camera / rendering | Auto-cut + blend to collisions/bottlenecks |
| F4 | **Scenario Verification** | `UScenarioVerificationComponent` | `scenario/` | AI-agent scenario verification | Live pass/fail verdict against agent criteria |

The four compose into one showcase loop:

```
AI agent issues a scenario WITH acceptance criteria (F4)
        │
        ▼
Sim runs ── AGV positions ──► Heatmap recolours the floor live (F1)
        │              └────► Status billboards track each AGV (F2)
        │
        ├─ collision / bottleneck event ──► Cinematic Director cuts the
        │                                    evaluator camera to the hotspot (F3)
        │
        ▼
Run ends ──► F4 evaluates criteria ──► PASS / FAIL verdict back to the agent,
                                        which explains the result in chat
```

---

## 2. F1 — Congestion Heatmap (`UCongestionHeatmapComponent`)

**Files:** `public/visualization/CongestionHeatmapComponent.h` · `private/visualization/CongestionHeatmapComponent.cpp`
**Type:** `UActorComponent` (attach to `AGVSimController` or a dedicated viz actor).

### Purpose
Render a live "traffic density" heatmap on the cell floor so an evaluator instantly sees *where*
congestion forms — the visual evidence behind the **Avg Wait Time** and **Bottleneck** KPIs.

### How it works (data-driven)
1. Each tick (throttled to ~10 Hz) it samples the world positions of all registered AGV actors.
2. It accumulates a coarse 2D density grid over a configured floor bounds rectangle, with temporal
   decay so stale heat fades (recent dwell weighs more than a vehicle that merely passed through).
3. The normalized grid is exposed two ways:
   - **Rendering hook:** writes the peak/normalized density and a hotspot world-location into a
     `UMaterialParameterCollection` (soft-referenced, optional) so a floor decal/material renders the
     heat. No asset is hard-required — if no MPC is set, the component still serves queries.
   - **Query API:** `GetNormalizedDensityAt(WorldLocation)` and `GetHottestCell()` for other systems
     (e.g. F3 can ask "where is the worst congestion right now?").

### Key API
```cpp
void RegisterAgv(AActor* Agv);                 // controller registers each spawned AGV
void SetFloorBounds(FVector Origin, FVector2D Size);
float GetNormalizedDensityAt(const FVector& WorldLocation) const; // 0..1
bool  GetHottestCell(FVector& OutWorldLocation, float& OutDensity) const;
UTexture2D* GetHeatTexture() const;             // runtime-generated grayscale density texture
```

**2026-06-09 update:** the rendering hook now includes a transient `HeatTexture` that the component
updates from the full density grid. Assign `M_FloorHeat` to the component's `FloorHeatMaterial` field
to let C++ create and size the floor decal automatically; `MPC_Congestion` is optional for hotspot
pulse/debug effects.

### Wiring
`AGVSimController::InitializeRuntimeSimulationActors()` → after spawning AGVs, `RegisterAgv(agv)` for
each and `SetFloorBounds(...)` from the cell boundary extent. Material wiring (decal + MPC) is an
editor step documented inline in the header.

### Showcase scenario
> *"Add one more AGV and rerun."* The agent triggers the run; as the extra vehicle loads the
> intersection, the floor blooms red around the crossing in real time — the evaluator sees the
> bottleneck *form* before the KPI table even updates.

---

## 3. F2 — Live Status Billboards (`UAGVStatusBillboardComponent`)

**Files:** `public/visualization/AGVStatusBillboardComponent.h` · `private/visualization/AGVStatusBillboardComponent.cpp`
**Type:** `USceneComponent` owning a child `UTextRenderComponent` (engine-only, no UMG asset needed).

### Purpose
Float a compact, always-readable status label above each AGV — `state · battery% · speed` — that
updates live and colour-codes by state (green = active, amber = waiting, red = collision). Makes the
3D scene self-describing for a non-expert viewer.

### How it works (data-driven)
- Attached to an `AAGVActor`; each tick (throttled) it reads the AGV's existing getters
  (`GetStateName`, `GetBatteryPercent`, `GetCurrentSpeed`, `GetDestinationLabel`) and rebuilds the
  label text + colour.
- The text faces the active camera (billboarding) so it stays readable from any viewpoint, including
  the F3 cinematic cuts and the per-AGV chase cameras.

### Key API
```cpp
void SetTrackedAgv(class AAGVActor* Agv);
void SetVisibleState(bool bVisible);   // hide for clean cinematic shots if desired
```

### Wiring
`AAGVActor` constructor creates and attaches one `UAGVStatusBillboardComponent` and calls
`SetTrackedAgv(this)`. Self-contained — no controller change required.

### Showcase scenario
> Panning the free camera across the cell, every vehicle announces itself: *"AGV-2 · WAITING · 71% ·
> 0.0 m/s"* turns amber the instant it queues at the intersection.

---

## 4. F3 — Cinematic Event Director (`UCinematicEventDirector`)

**Files:** `public/cinematics/CinematicEventDirector.h` · `private/cinematics/CinematicEventDirector.cpp`
**Type:** `UActorComponent` (attach to `AGVSimController`).

### Purpose
Turn the simulation into an *auto-directed* presentation for evaluators: when a noteworthy event
fires (collision, bottleneck), the camera smoothly cuts to frame the hotspot, dwells, then returns to
the overview — no manual camera driving during a demo.

### How it works (data-driven, event-driven)
- The controller calls `FocusOnEvent(EEventKind, WorldLocation, FocusActor)` from its existing
  `NotifyCollision` / `EmitBottleneckEvent` paths.
- The director computes a framing transform (offset/height/pitch by event kind), spawns or repositions
  a managed `ACameraActor`, and calls `APlayerController::SetViewTargetWithBlend` with a configurable
  blend time. After a dwell timeout it blends back to the previous view target (overview or the camera
  that was active before the cut).
- Event priority + a minimum-hold prevents thrashing when events arrive in bursts (a higher-severity
  collision can pre-empt a bottleneck cut; equal events queue).

### Key API
```cpp
void FocusOnEvent(ECinematicEventKind Kind, const FVector& WorldLocation, AActor* FocusActor);
void SetOverviewTarget(AActor* Overview);   // where to return to
void SetEnabled(bool bEnabled);             // evaluators can toggle auto-direction
```

### Wiring
`AGVSimController` constructs the director, sets the overview target on `BeginPlay`, and calls
`FocusOnEvent(...)` inside `NotifyCollision` and `EmitBottleneckEvent`. Co-exists with the manual
`POST /camera/select` path — a manual selection cancels auto-direction until re-enabled.

### Showcase scenario
> Mid-run, two AGVs clip at the crossing. Without a touch on the controls, the view snaps — with a
> half-second blend — to a low dramatic angle on the collision, holds for three seconds, then eases
> back to the cell overview. The evaluator never misses the critical moment.

---

## 5. F4 — Scenario Verification (`UScenarioVerificationComponent`)

**Files:** `public/scenario/ScenarioVerificationComponent.h` · `private/scenario/ScenarioVerificationComponent.cpp`
**Type:** `UActorComponent` (attach to `AGVSimController`). **This is the AI-agent feature.**

### Purpose
Elevate the agent from *"start a sim"* to *"design a verifiable experiment."* The agent attaches a
set of **acceptance criteria** to a run; the engine evaluates them against live + final KPIs and emits
a machine-readable **verdict** (`PASS` / `FAIL` per-criterion + overall) that the agent reads back and
explains in chat. This is the "pre-verification" promise in [PROJECT_IDEA.md](PROJECT_IDEA.md) made
literal in the engine.

### Data model
```cpp
enum class EScenarioMetric  : uint8 { Throughput, AvgWaitSec, CollisionCount, UptimeRatio, ActiveAgvs };
enum class EScenarioCompare : uint8 { GreaterOrEqual, LessOrEqual, Equal };

struct FScenarioCheck {                 // one acceptance criterion
    FString Label;                      // "throughput ≥ 70/h"
    EScenarioMetric Metric;
    EScenarioCompare Comparator;
    float Threshold;
};

struct FScenarioVerdict {               // result
    bool bPassed;                       // overall (all checks pass)
    TArray<FString> PassedLabels;
    TArray<FString> FailedLabels;
};
```

### How it works
1. The agent's `start_simulation` / `run_station_task` command carries an optional `acceptance` array
   (metric, comparator, threshold). The backend forwards it; the controller calls
   `LoadChecks(Checks)`.
2. The component evaluates checks against a `FProcessKpiSnapshot` (the same compact record already
   produced for telemetry/KPI) — **live** each evaluation tick (for early-abort on a hard violation)
   and **finally** at run completion.
3. It produces a `FScenarioVerdict`; the controller serializes it into the completion/event payload so
   the agent can answer *"did my proposed change meet the bar?"*

### Key API
```cpp
void LoadChecks(const TArray<FScenarioCheck>& Checks);
FScenarioVerdict Evaluate(const FProcessKpiSnapshot& Snapshot) const;
bool HasHardViolation(const FProcessKpiSnapshot& Snapshot) const;  // optional early-abort
```

### Backend / API touchpoint (wired 2026-06-07)
- `POST /sim/start` (and the `start_simulation` agent tool schema) takes an optional `acceptance[]`
  field (`metric`/`comparator`/`threshold`/`label`); `ToolRouter._normalize_acceptance` validates it.
  See [spec_api.md](spec_api.md) §3.1 / [spec_virtual_process.md](spec_virtual_process.md). Engine-side
  parsing lives in `AGVSimController` (boundary), not in this domain component.
- The completion payload (`robot.command.completed`) carries a `verdict` object; the report agent reads
  it back into chat. See [spec_api.md](spec_api.md) §3.3.

### Showcase scenario
> *"If I add an AGV, throughput must stay above 70/h and average wait under 12 s, with zero
> collisions."* The agent encodes three criteria, runs the sim, and reports back: **"PASS — throughput
> 74.9/h, wait 11.4 s; but 1 collision occurred → FAIL on safety. Recommend priority-loaded policy."**
> The verification is the deliverable, not just the number.

---

## 6. Implementation Status & Phasing

| Layer | Done | Follow-up |
|---|---|---|
| C++ classes | F1–F4 scaffolded + wired into `AGVSimController` lifecycle | — |
| Rendering (F1) | Component owned, AGVs registered, floor bounds set; query API live | Author `M_FloorHeat` decal + `MPC_Congestion` (editor) |
| Camera (F3) | Framing math + blend API; auto-cut from collision/bottleneck | Tune blend curves, dwell, severity in PIE |
| AI agent (F4) | **Done.** Verdict data model + eval logic; `acceptance[]` in agent tool schema + UE5 parse; `verdict` in completion payload; report agent surfaces PASS/FAIL | — |
| HUD (F5) | **UMG widget** (`UVcoreHudWidget`) replaces the Canvas/text HUD; shows status, progress, counters, event ticker, and the F4 verdict | Optionally restyle via a `WBP_VcoreHud` |

### F4 end-to-end (2026-06-07)
- **Backend:** `START_SIMULATION` tool contract gains an optional `acceptance[]` (`metric`, `comparator`,
  `threshold`, optional `label`); `ToolRouter` normalizes/validates it (drops malformed entries, fills
  default labels). The array flows untouched through `parameters` to UE5 `POST /sim/start`.
- **Engine:** `AGVSimController` owns a `UScenarioVerificationComponent`, parses `acceptance` into
  `FScenarioCheck`s at run start (`LoadChecks`), and at completion evaluates them against the final KPIs
  (`FProcessKpiSnapshot`) into a `verdict` serialized in the runtime report and forwarded on the
  `robot.command.completed` payload. The verdict also feeds the F5 HUD.
- **Chat read-back:** `_compact_event_context` now passes `verdict` + `kpis` to the report LLM, the
  report prompt instructs a 합격/불합격 summary, and both rule-based fallbacks append a one-line verdict
  (`format_verdict_summary`).

**Definition of done (Phase 9):** in a live run the floor heatmap reacts to AGV density, billboards
track every AGV, a collision auto-cuts the camera, and an agent-issued acceptance set yields a
PASS/FAIL verdict surfaced in chat. **F4 is code-complete; remaining Phase 9 items are F1/F3 editor
tuning.** See [guide_unreal_editor_f4_hud.md](guide_unreal_editor_f4_hud.md) for the editor steps.
