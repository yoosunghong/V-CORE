# Zone Camera Buttons Do Not Switch View

## Summary

The web frontend `Zone1`, `Zone2`, and `Zone3` buttons may successfully call UE5's `/camera/select` endpoint but fail to switch the Pixel Streaming view. The final root cause was that the assigned zone cameras lived in a separate streaming level package that was not loaded in the runtime world when the button was pressed.

The fix was to store zone camera targets as soft actor references on `AGVSimController`, resolve them at click time, and request-load the camera streaming level before retrying the camera switch.

## Symptoms

The frontend button request reaches UE, but the viewport does not move to the requested zone camera.

Common log signatures:

```text
LogTemp: Warning: AGVSimController: FindZoneCamera no match for 'Zone2' among 0 camera actor(s)
LogTemp: Warning: AGVSimController: No camera tagged Zone2 for zone-2
```

After switching to explicit soft camera references, the more precise failure was:

```text
LogTemp: Warning: AGVSimController: Configured camera target for 'Zone1' is assigned but not loaded; falling back to tag lookup.
LogTemp: Warning: AGVSimController: FindZoneCamera no match for 'Zone1' among 5040 actor(s), 1 camera candidate(s).
```

When trying hard `AActor*` references across levels, the editor also reported:

```text
Warning: Illegal TEXT reference to a private object in external package
(CineCameraActor /Game/Warehouse/Scene/StreamingLevels/Cameras.Cameras:PersistentLevel.CineCameraActor_6)
from referencer
(BP_AGVSimController_C /Game/GAME/Maps/Warehouse.Warehouse:PersistentLevel.BP_AGVSimController_C_3).
Import failed...
```

## Root Cause

There were three separate problems that looked similar from the frontend:

1. The first implementation searched only `TActorIterator<ACameraActor>`. This was too narrow for Blueprint-wrapped cameras, component-based camera targets, and other camera target shapes.
2. Hard `AActor*` references cannot legally point from the persistent level's `BP_AGVSimController` to private actor instances inside another streaming level package.
3. `TSoftObjectPtr<AActor>` can store those cross-level camera references, but `.Get()` only resolves after the camera's streaming level is loaded in the runtime world.

The decisive clue was:

```text
Configured camera target for 'Zone1' is assigned but not loaded
```

That means the editor assignment was valid, but the runtime world had not loaded the camera level yet.

## Fix

`AGVSimController` now exposes three soft camera target fields:

```cpp
UPROPERTY(EditInstanceOnly, Category="VCORE|Camera")
TSoftObjectPtr<AActor> Zone1CameraTarget;

UPROPERTY(EditInstanceOnly, Category="VCORE|Camera")
TSoftObjectPtr<AActor> Zone2CameraTarget;

UPROPERTY(EditInstanceOnly, Category="VCORE|Camera")
TSoftObjectPtr<AActor> Zone3CameraTarget;
```

`FindZoneCamera()` first tries the assigned soft reference. If the actor is already loaded and is a valid camera target, UE switches to it immediately.

If the soft reference is assigned but unresolved, `RequestLoadConfiguredZoneCameraLevel()` derives the streaming level package from the soft actor path, calls:

```cpp
UGameplayStatics::LoadStreamLevel(World, FName(*LevelPackageName), true, false, LatentInfo);
```

Then it retries `SelectViewTarget()` shortly after the level load request.

The old tag/name scan remains only as a compatibility fallback when no explicit camera target is assigned.

## Editor Setup

1. Fully rebuild the project after the C++ changes.
2. Restart the Unreal Editor. Do not rely on Live Coding for reflected `UPROPERTY` layout changes.
3. Select the placed `BP_AGVSimController` actor.
4. In `VCORE|Camera`, assign:
   - `Zone1CameraTarget`
   - `Zone2CameraTarget`
   - `Zone3CameraTarget`
5. Save the level.
6. Run PIE or standalone and click the web `Zone1`, `Zone2`, or `Zone3` buttons.

## Expected Logs

On first click, if the camera streaming level is not loaded yet:

```text
LogTemp: AGVSimController: Requested streaming level '/Game/Warehouse/Scene/StreamingLevels/Cameras' for configured camera target 'Zone1' (...)
```

After the retry, the view should switch to the assigned camera.

If it still fails, check whether the logged level package is the actual streaming level package and whether that level is allowed to load at runtime.

## Lessons Learned

- Actor tags are useful as a fallback, but explicit camera fields are better for operator UI camera buttons.
- Use `TSoftObjectPtr<AActor>` for references to actors in another streaming level package.
- A soft actor reference being assigned does not mean the actor is loaded.
- New or changed `UPROPERTY` members require a full rebuild and editor restart; Live Coding is not reliable for this case.
