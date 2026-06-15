# AGV Nameplate Widget Setup

This project provides `UAGVNameplateWidget`, a C++ `UUserWidget` base class for the AGV billboard-style nameplate.

## Widget Blueprint

1. Create a Widget Blueprint in `Content` and set its parent class to `AGVNameplateWidget`.
2. In the widget Hierarchy, add these widgets named **exactly** (names must match because the C++
   class binds them via `meta=(BindWidget)` / `BindWidgetOptional`):
   - `TXT_AGVName` — `TextBlock` (required).
   - `TXT_Task` — `TextBlock`. The AGV's current activity, e.g. `LOADING`. **This is the
     renamed former `TXT_Status`** — if you are updating an existing nameplate WBP, rename its
     `TXT_Status` TextBlock to `TXT_Task`.
   - `TXT_Status` — `TextBlock`. Now the online indicator: C++ sets it to `Online` (green) while
     the AGV is running and `Offline` (red) when stopped, and overrides its colour each refresh.
   - `PB_Battery` — `ProgressBar`. Filled to the AGV's battery (0..1). Optional fill/background
     tint is up to the designer; the C++ only drives `Percent`.
3. Suggested layout:
   - Root: `Canvas Panel` or `Size Box`.
   - Size Box: width `260`, height `90`.
   - Add a vertical box centered in the root.
   - `TXT_AGVName`: larger or bold text for values like `AGV AGV-1`.
   - `TXT_Task`: smaller activity text such as `LOADING`.
   - `TXT_Status`: small bold text; initial colour does not matter (C++ recolours it green/red).
   - `PB_Battery`: a thin horizontal bar under the text rows.
   - Use a translucent dark background if readability over the scene is poor.

> The `TXT_Task`, `TXT_Status` and `PB_Battery` binds are **optional** (`BindWidgetOptional`), so a
> not-yet-rewired Blueprint still compiles — those slots simply stay blank until you add the widgets
> with the exact names above.

## AGV Blueprint

1. Open the AGV Blueprint derived from `AAGVActor`.
2. Select the `NameplateWidget` component.
3. Set `Widget Class` to the WBP created above.
4. Recommended component settings:
   - `Space`: `Screen` for a camera-facing HUD-style billboard.
   - `Draw Size`: `260 x 90`.
   - `Relative Location`: around `Z = 150`, adjusted above the AGV mesh.
   - `Collision`: disabled.
5. If using `Space = World`, keep `Face Nameplate To Camera In World Space` enabled on the AGV actor so C++ rotates the widget toward the active player camera each tick.

At runtime, `AAGVActor::BeginPlay` casts the component's widget to `UAGVNameplateWidget` and
initializes it. `AAGVActor::UpdateNameplateWidget` calls `SetAGVInfo(Name, Task, bOnline,
BatteryPercent)` on every tick while the AGV is running (and on each state change), so the task
label, the green/red Online·Offline status, and the battery bar all stay live.
