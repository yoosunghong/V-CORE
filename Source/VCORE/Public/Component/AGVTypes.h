#pragma once

#include "CoreMinimal.h"
#include "AGVTypes.generated.h"

UENUM()
enum class EAGVState : uint8
{
    Idle,
    MovingToPickup,
    Loading,
    MovingToDropoff,
    Unloading,
    WaitingAtSection,
    StoppedCollision,
    MovingToStation,
    // Offline AGV: authored in the level but excluded from the current run (index >= AgvCount).
    // Fully reset (home pose, full battery, no task) and surfaced to the dashboard in red.
    StoppedOperation
};
