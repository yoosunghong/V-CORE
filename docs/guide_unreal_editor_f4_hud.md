# Unreal Editor Work Guide — F4 Scenario Verification + Production HUD

> ⚠️ **Partly superseded (2026-06-08).** The in-viewport UE5 HUD (`AVCOREHud` + `UVcoreHudWidget`)
> was **removed** and migrated to the web overlay (`VcoreHud` in `chat-web`), fed by the process
> telemetry frame — see [spec_unreal.md](spec_unreal.md) §7.1. **Skip every HUD step in this guide**
> (`AVCOREHud`, `WBP_VcoreHud`, setting `HUDClass`, the `meta=(BindWidget)` restyle). The F4 scenario
> **verification** content below is still valid; the GameMode is still `AVirtualProcessGameMode` but it
> no longer installs a HUD, so no HUD-related editor step is needed.

**Project:** VCORE — UE5 subsystem (`Source/VCORE`)
**Written:** 2026-06-07
**Audience:** whoever opens the project in the Unreal Editor after the F4 + HUD code landed.

This guide lists exactly what **you** must do in the Unreal Editor — the code is done and committed
to Perforce, but C++ changes need a compile and a few one-time editor/asset/config steps before the
features are live in PIE and the Pixel Stream.

> **Why this doc exists.** The agent cannot build the engine, launch the editor, author assets, or
> flip per-map config. Everything below is one of those. Steps are ordered; do them top-to-bottom.

---

## 0. TL;DR checklist

- [x] **Compile** the C++ (Live Coding or full rebuild) — new classes: `UScenarioVerificationComponent`
      wiring, `UVcoreHudWidget`, rewritten `AVCOREHud`.
- [x] **Set the GameMode** so the HUD shows: make `AVirtualProcessGameMode` the Warehouse map's
      *GameMode Override* (or the project's *GlobalDefaultGameMode*).
- [ ] **Verify in PIE:** HUD panel appears top-left; run a sim from chat with acceptance criteria and
      confirm a PASS/FAIL badge appears on the HUD and a 합격/불합격 line appears in chat.
- [ ] *(Optional)* Author `WBP_VcoreHud` to restyle the HUD, and `MPC_Congestion` + `M_FloorHeat` for F1.

If you only do the **bold** items, F4 and the new HUD are fully functional. The optional items are
visual polish.

---

## 1. Compile the C++

The following files changed/were added (all under `Source/VCORE`):

| File | What changed |
|---|---|
| `private/controller/AGVSimController.cpp` · `public/controller/AGVSimController.h` | Owns `UScenarioVerificationComponent`; parses `acceptance[]` → `FScenarioCheck`; emits `verdict`; retains last verdict for the HUD |
| `public/scenario/ScenarioVerificationComponent.*` | (already existed) the F4 evaluator — unchanged |
| `public/core/VcoreHudWidget.h` · `private/core/VcoreHudWidget.cpp` | **New** UMG widget that builds its tree in C++ |
| `public/core/VCOREHud.*` | Rewritten: owns the widget, feeds it a snapshot on a ~15 Hz timer (was Canvas drawing) |
| `VCORE.Build.cs` | Added `SlateCore` dependency |

**How to compile:**
1. Close the editor if a full rebuild is preferred (safer for a `Build.cs` change + new `UCLASS`es).
2. Right-click `VCORE.uproject` → **Generate Visual Studio project files** (picks up new files).
3. Build the **Development Editor** target in your IDE, *or* use **Live Coding** (Ctrl+Alt+F11) if the
   editor is open — but note: adding a new `Build.cs` dependency (`SlateCore`) and brand-new `UCLASS`es
   is more reliable with a **full editor restart + rebuild** than Live Coding. If Live Coding errors,
   restart and do a normal build.

**Expected result:** clean compile. If you hit a missing-include or module error, it is almost
certainly the `SlateCore` dependency not being picked up — regenerate project files and rebuild.

---

## 2. Activate the HUD (required) — set the GameMode

The HUD is installed by `AVirtualProcessGameMode` via its `HUDClass`. It is intentionally **not** forced
globally, so you must opt the map in:

**Option A — per-map (recommended for the demo):**
1. Open the **Warehouse** map (the AGV cell level you run the demo in).
2. **Window → World Settings**.
3. Under **Game Mode → GameMode Override**, select **`VirtualProcessGameMode`** (`AVirtualProcessGameMode`).
4. Save the map.

**Option B — project-wide:**
1. **Edit → Project Settings → Maps & Modes**.
2. Set **Default GameMode** to `VirtualProcessGameMode`.
3. (Only do this if every map should use it — Option A is cleaner for the demo.)

> There must be exactly one `AAGVSimController` actor in the level (it already drives the sim). The HUD
> finds it automatically; no wiring needed.

**Verify:** Press **Play**. A dark panel should appear at the top-left showing
`VCORE VIRTUAL PROCESS · IDLE`, a progress bar, and `Tasks 0  Collisions 0`. If nothing shows, see
§5 Troubleshooting.

---

## 3. Verify F4 end-to-end (required)

F4 needs no editor assets — only the running backend + UE5. With the stack up (`web/docker-compose.yml`)
and PIE running with the GameMode set:

1. In the chat (chat-web overlay or API), issue a scenario that frames a **verifiable goal**, e.g.:
   > "AGV를 4대로 시뮬레이션 돌리고, 처리량은 시간당 70 이상, 평균 대기 12초 이하, 충돌 0건이어야 해."
   (or English: *"Run the sim with 4 AGVs; throughput must stay above 70/h, average wait under 12s,
   and zero collisions."*)
2. The agent should call `start_simulation` with an `acceptance[]` array. The sim runs.
3. On completion:
   - **In UE5:** the HUD shows an **ACCEPTANCE PASS** (green) or **FAIL** (red) badge with `(passed/total)`.
   - **In chat:** the report message states **합격(PASS)** or **불합격(FAIL)** and cites which criteria
     passed/failed with KPI values.

**If the LLM doesn't emit `acceptance` reliably** (small local models sometimes omit optional tool
fields), you can prove the pipe directly by POSTing to UE5:

```bash
curl -X POST http://localhost:7777/sim/start \
  -H "Content-Type: application/json" -H "X-AGV-API-Key: <your AGV_API_KEY>" \
  -d '{
    "run_id": "ftest-1", "session_id": "scenario-control", "command_id": "ftest-1",
    "parameters": {
      "agv_count": 4, "speed_multiplier": 4.0,
      "acceptance": [
        {"label":"throughput >= 70/h","metric":"throughput","comparator":">=","threshold":70},
        {"label":"no collisions","metric":"collision_count","comparator":"==","threshold":0}
      ]
    }
  }'
```

Watch the UE5 **Output Log** and the HUD verdict badge when the run completes.

> **Metric names** (must match exactly): `throughput`, `avg_wait_sec`, `collision_count`,
> `uptime_ratio`, `active_agvs`. **Comparators:** `>=`, `<=`, `==`. The UE parser also tolerates a few
> aliases (e.g. `avg_wait_time`, `collisions`, `gte`/`lte`/`eq`), but prefer the canonical set.

---

## 4. Optional polish (skip for a working demo)

### 4.1 Restyle the HUD with a Widget Blueprint

The HUD already works with **zero assets** — `UVcoreHudWidget` builds its own widget tree in C++. If a
designer wants to restyle it (fonts, colours, layout, a logo), author a WBP:

1. **Content Browser → Add → User Interface → Widget Blueprint.**
2. When prompted for the parent class (or **File → Reparent Blueprint** afterwards), choose
   **`VcoreHudWidget`**. Name it **`WBP_VcoreHud`**.
3. > **Important:** the C++ layout (`RebuildWidget` / `BuildLayout`) only runs when the widget tree is
     *empty*. If you author a tree in the WBP designer, the C++ tree is **not** added, and the live
     `UpdateFromSnapshot` calls will no-op (its bound pointers stay null). So there are two clean modes:
     >
     > - **Code-owned (default):** don't assign a WBP; leave `HudWidgetClass` at `UVcoreHudWidget`.
     >   You get the C++ panel. Restyle by editing colours/fonts in `VcoreHudWidget.cpp`.
     > - **Designer-owned:** to drive a hand-built WBP from code, the widget needs named child widgets
     >   bound back to C++. That requires converting the private `UPROPERTY(Transient)` pointers in
     >   `VcoreHudWidget.h` to `UPROPERTY(meta=(BindWidget))` with **matching widget names**
     >   (`StatusText`, `MetaText`, `ProgressBar`, `CountersText`, `VerdictText`, `VerdictBorder`,
     >   `EventsBox`) and removing the programmatic `BuildLayout`. This is a code change — ask the dev
     >   before going this route.
4. If you keep the **code-owned** default but still want the WBP class selected (e.g. to set it as a
   Blueprint for other reasons), set it on the HUD: select your `AVCOREHud` (or subclass it as a BP)
   and set **HudWidgetClass** = `WBP_VcoreHud`. For the demo this is unnecessary.

**Recommendation for the portfolio demo:** keep the **code-owned** HUD. It is self-contained, renders
identically in PIE and the Pixel Stream, and needs no asset management. Treat the WBP path as a future
designer hand-off, not a demo requirement.

### 4.2 F1 Congestion heatmap material (separate feature)

Not required for F4/HUD, but listed here since it's the remaining Phase 9 editor task:
1. Create a **decal material** `M_FloorHeat`.
   - Material Domain: **Deferred Decal**
   - Blend Mode: **Translucent** (or Alpha Composite if you want softer compositing)
   - Decal Blend Mode: **Translucent / Emissive**
   - Add a `Texture Object` or `Texture Sample Parameter2D` named `HeatTexture`. This is supplied
     at runtime by `UCongestionHeatmapComponent`; no imported heatmap texture is needed.
   - Use decal UVs to sample `HeatTexture`, run it through a colour ramp
     (`0 = transparent/blue`, `0.5 = yellow/orange`, `1 = red`), and drive Emissive/Opacity.
2. Optional: create **Material Parameter Collection** `MPC_Congestion` with scalar `PeakDensity` and
   vector `HotspotLocation` if you also want a single hottest-point pulse, ring, or debug marker.
3. In the level, select the `AGVSimController`, then its `CongestionHeatmap` component:
   - Set **Floor Heat Material** = `M_FloorHeat`.
   - Leave **Create Managed Decal** enabled unless you want to place your own `ADecalActor`.
   - If using the optional MPC effect, set **Heat Parameter Collection** = `MPC_Congestion`.
   The component sizes and positions the managed decal from `HeatmapFloorSize`, and updates the
   `HeatTexture` parameter every sample tick.
4. If you prefer a manually placed decal, disable **Create Managed Decal**, place an `ADecalActor`
   over the cell floor, assign a material instance of `M_FloorHeat`, and bind its `HeatTexture`
   parameter from Blueprint using `CongestionHeatmap.GetHeatTexture()`.
5. Texture to obtain: only a small optional **1D gradient/ramp LUT** if you want artist-controlled
   colours. The density texture itself is generated by C++ at runtime, so do not import a baked
   heatmap image.
   (See [spec_portfolio_features.md](spec_portfolio_features.md) §2.)

---

## 5. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| No HUD panel in PIE | GameMode not set (§2), or no `AAGVSimController` in the level. Check **World Settings → GameMode Override**. |
| HUD shows but never updates | The widget tree wasn't built (a WBP with a hand-authored tree was assigned — see §4.1). Revert `HudWidgetClass` to `UVcoreHudWidget`. |
| Compile error about `SlateCore`/UMG includes | Regenerate VS project files and do a full rebuild — the new `Build.cs` dependency must be picked up. |
| Verdict badge never appears | The run carried no `acceptance` criteria (badge only shows when criteria exist), or the LLM didn't emit them — prove the pipe with the curl in §3. |
| Chat report omits PASS/FAIL | Confirm the completion event payload contains `verdict` (UE5 Output Log), and that the backend image includes the updated `report_system.txt` + `llm_gateway.py` (rebuild the `chatbot-backend` container). |

---

## 6. What the agent already did (no action needed)

- Wired `UScenarioVerificationComponent` into `AGVSimController` (construct, `LoadChecks`, `Evaluate`,
  serialize `verdict`, clear on reset).
- Added `acceptance[]` to the `START_SIMULATION` tool contract + router validation/normalization.
- Forwarded the `verdict` on the `robot.command.completed` payload and surfaced PASS/FAIL in the report
  agent (LLM prompt + rule-based fallbacks).
- Replaced the Canvas HUD with the `UVcoreHudWidget` UMG widget and rewired `AVCOREHud` to drive it;
  added the F4 verdict line to the HUD snapshot.
- Backend unit tests for the acceptance/verdict logic: `tests/test_scenario_verification.py` (6 pass).
